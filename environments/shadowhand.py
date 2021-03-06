#!/usr/bin/env python
"""ShadowHand Environment Wrappers."""
import os

import numpy as np
from gym import utils, spaces
from gym.envs.robotics import HandReachEnv, HandBlockEnv
from gym.envs.robotics.hand import manipulate
from gym.envs.robotics.hand.reach import DEFAULT_INITIAL_QPOS, FINGERTIP_SITE_NAMES
from gym.envs.robotics.utils import robot_get_obs

from utilities.const import VISION_WH, N_SUBSTEPS

MANIPULATE_BLOCK_XML = os.path.join(os.path.abspath(os.path.dirname(os.path.realpath(__file__))),
                                    "assets/hand",
                                    'manipulate_block_touch_sensors.xml')

MANIPULATE_EGG_XML = os.path.join(os.path.abspath(os.path.dirname(os.path.realpath(__file__))),
                                  "assets/hand",
                                  'manipulate_egg_touch_sensors.xml')


# DEFAULT_INITIAL_QPOS = {k: v * 0 for k, v in DEFAULT_INITIAL_QPOS.items()}


def get_palm_position(sim):
    """Return the robotic hand's palm's center."""
    palm_idx = sim.model.body_names.index("robot0:palm")
    return np.array(sim.model.body_pos[palm_idx])


def get_fingertip_distance(ft_a, ft_b):
    """Return the distance between two vectors representing finger tip positions."""
    assert ft_a.shape == ft_b.shape
    return np.linalg.norm(ft_a - ft_b, axis=-1)


class ShadowHand(manipulate.ManipulateEnv):
    """Adjusted version of ManipulateTouchSensorsEnv Environment in the gym package to fit the projects needs."""

    def __init__(self, model_path, target_position, target_rotation, target_position_range, reward_type,
                 initial_qpos={}, randomize_initial_position=True, randomize_initial_rotation=True,
                 distance_threshold=0.01, rotation_threshold=0.1, n_substeps=N_SUBSTEPS, relative_control=True,
                 ignore_z_target_rotation=False, touch_visualisation="off", touch_get_obs="sensordata",
                 visual_input: bool = False, max_steps=100):
        """Initializes a new Hand manipulation environment with touch sensors.

        Args:
            touch_visualisation (string): how touch sensor sites are visualised
                - "on_touch": shows touch sensor sites only when touch values > 0
                - "always": always shows touch sensor sites
                - "off" or else: does not show touch sensor sites
            touch_get_obs (string): touch sensor readings
                - "boolean": returns 1 if touch sensor reading != 0.0 else 0
                - "sensordata": returns original touch sensor readings from self.sim.data.sensordata[id]
                - "log": returns log(x+1) touch sensor readings from self.sim.data.sensordata[id]
                - "off" or else: does not add touch sensor readings to the observation
            visual_input (bool): indicator whether the environment should return frames (True) or the exact object
                position (False)
            max_steps (int): maximum number of steps before episode is ended
        """

        if visual_input:
            # init rendering [IMPORTANT]
            from mujoco_py import GlfwContext
            GlfwContext(offscreen=True)  # in newer version of gym use quiet=True to silence this

        self.touch_visualisation = touch_visualisation
        self.touch_get_obs = touch_get_obs
        self.visual_input = visual_input
        self.touch_color = [1, 0, 0, 0.5]
        self.notouch_color = [0, 0.5, 0, 0.2]
        self.total_steps = 0
        self.max_steps = max_steps

        manipulate.ManipulateEnv.__init__(
            self, model_path, target_position, target_rotation,
            target_position_range, reward_type, initial_qpos=initial_qpos,
            randomize_initial_position=randomize_initial_position,
            randomize_initial_rotation=randomize_initial_rotation,
            distance_threshold=distance_threshold, rotation_threshold=rotation_threshold, n_substeps=n_substeps,
            relative_control=relative_control,
            ignore_z_target_rotation=ignore_z_target_rotation,
        )

        self._touch_sensor_id_site_id = []
        self._touch_sensor_id = []
        # get touch sensor site names and their ids
        for k, v in self.sim.model._sensor_name2id.items():
            if 'robot0:TS_' in k:
                self._touch_sensor_id_site_id.append(
                    (v, self.sim.model._site_name2id[k.replace('robot0:TS_', 'robot0:T_')]))
                self._touch_sensor_id.append(v)

        # set touch sensors rgba values
        if self.touch_visualisation == 'off':
            for _, site_id in self._touch_sensor_id_site_id:
                self.sim.model.site_rgba[site_id][3] = 0.0
        elif self.touch_visualisation == 'always':
            pass

        # set hand and background colors
        self.sim.model.mat_rgba[2] = np.array([16, 18, 35, 255]) / 255
        self.sim.model.mat_rgba[4] = np.array([104, 143, 71, 255]) / 255
        self.sim.model.geom_rgba[48] = np.array([0.5, 0.5, 0.5, 0])

        # set observation space
        self.observation_space = self._determine_observation_space()

    def _determine_observation_space(self):
        obs = self._get_obs()
        return spaces.Dict(dict(
            desired_goal=spaces.Box(-np.inf, np.inf, shape=obs['desired_goal'].shape, dtype='float32'),
            achieved_goal=spaces.Box(-np.inf, np.inf, shape=obs['achieved_goal'].shape, dtype='float32'),
            observation=spaces.Tuple((
                spaces.Box(-np.inf, np.inf, shape=obs["observation"][0].shape, dtype='float32'),  # visual/object
                spaces.Box(-np.inf, np.inf, shape=obs["observation"][1].shape, dtype='float32'),  # proprioception
                spaces.Box(-np.inf, np.inf, shape=obs["observation"][2].shape, dtype='float32'),  # touch sensors
                spaces.Box(-np.inf, np.inf, shape=obs["observation"][3].shape, dtype='float32'),  # goal
            ))
        ))

    def _viewer_setup(self):
        super()._viewer_setup()

        # rotate camera to top down view
        self.viewer.cam.distance = 0.4  # zoom in
        self.viewer.cam.azimuth = -90.0  # top down view
        self.viewer.cam.elevation = -90.0  # top down view
        self.viewer.cam.lookat[1] -= 0.03  # slightly move forward

    def _render_callback(self):
        super()._render_callback()
        if self.touch_visualisation == 'on_touch':
            for touch_sensor_id, site_id in self._touch_sensor_id_site_id:
                if self.sim.data.sensordata[touch_sensor_id] != 0.0:
                    self.sim.model.site_rgba[site_id] = self.touch_color
                else:
                    self.sim.model.site_rgba[site_id] = self.notouch_color

    def _get_obs(self):
        # "primary" information, either this is the visual frame or the object position and velocity
        achieved_goal = self._get_achieved_goal().ravel()
        if self.visual_input:
            primary = self.render(mode="rgb_array", height=VISION_WH, width=VISION_WH)
        else:
            object_vel = self.sim.data.get_joint_qvel('object:joint')
            primary = np.concatenate([achieved_goal, object_vel])

        # get proprioceptive information (positions of joints)
        robot_pos, robot_vel = manipulate.robot_get_obs(self.sim)
        proprioception = np.concatenate([robot_pos, robot_vel])

        # touch sensor information
        if self.touch_get_obs == 'sensordata':
            touch = self.sim.data.sensordata[self._touch_sensor_id]
        else:
            raise NotImplementedError("Only sensor data supported atm, sorry.")

        return {
            "observation": np.array((primary.copy(), proprioception.copy(), touch.copy(), self.goal.ravel().copy())),
            "achieved_goal": achieved_goal.copy(),
            "desired_goal": self.goal.ravel().copy(),
        }

    def _is_success(self, achieved_goal, desired_goal):
        """We determine success only by means of rotational goals."""
        _, d_rot = self._goal_distance(achieved_goal, desired_goal)
        return (d_rot < self.rotation_threshold).astype(np.float32)

    def _is_dropped(self) -> bool:
        """Heuristically determine whether the object still is in the hand."""

        # determin object center position
        obj_center_idx = self.sim.model.site_name2id('object:center')
        obj_center_pos = self.sim.data.site_xpos[obj_center_idx]

        # determine palm center position
        palm_center_pos = get_palm_position(self.sim)

        dropped = (
                obj_center_pos[2] < palm_center_pos[2]  # z axis of object smaller than that of palm
            # we could add smth like checking for contacts between palm and object here, but the above works
            # pretty well already tbh
        )

        return dropped

    def step(self, action):
        """Make step in environment."""
        self.total_steps += 1
        obs, reward, done, info = super().step(action)
        dropped = self._is_dropped()
        done = done or dropped or self.total_steps >= self.max_steps

        return obs, reward, done, info

    def reset(self):
        """Reset the environment."""
        self.total_steps = 0
        return super().reset()

    def compute_reward(self, achieved_goal, goal, info):
        """Compute the reward."""
        success = self._is_success(achieved_goal, goal).astype(np.float32)
        _, d_rot = self._goal_distance(achieved_goal, goal)

        return (- d_rot  # convergence to goal reward
                - 1  # constant punishment to encourage fast solutions
                + success * 5  # reward for finishing
                + 20 * self._is_dropped())  # dropping penalty


class ShadowHandBlock(ShadowHand, utils.EzPickle):
    """ShadowHand Environment with a Block as an object."""

    def __init__(self, target_position='ignore', target_rotation='xyz', touch_get_obs='sensordata',
                 reward_type='dense', visual_input: bool = False, max_steps=100):
        utils.EzPickle.__init__(self, target_position, target_rotation, touch_get_obs, reward_type)
        ShadowHand.__init__(self,
                            model_path=MANIPULATE_BLOCK_XML,
                            touch_get_obs=touch_get_obs,
                            target_rotation=target_rotation,
                            target_position=target_position,
                            target_position_range=np.array([(-0.04, 0.04), (-0.06, 0.02), (0.0, 0.06)]),
                            reward_type=reward_type,
                            visual_input=visual_input,
                            max_steps=max_steps)


class ShadowHandEgg(ShadowHand, utils.EzPickle):
    """ShadowHand Environment with an Egg as an object."""

    def __init__(self, target_position='ignore', target_rotation='xyz', touch_get_obs='sensordata',
                 reward_type='dense', visual_input: bool = False, max_steps=100):
        utils.EzPickle.__init__(self, target_position, target_rotation, touch_get_obs, reward_type)
        ShadowHand.__init__(self,
                            model_path=MANIPULATE_EGG_XML,
                            touch_get_obs=touch_get_obs,
                            target_rotation=target_rotation,
                            target_position=target_position,
                            target_position_range=np.array([(-0.04, 0.04), (-0.06, 0.02), (0.0, 0.06)]),
                            reward_type=reward_type,
                            visual_input=visual_input,
                            max_steps=max_steps)


# RELATED HAND TASKS

class ShadowHandReach(HandReachEnv):
    """Simpler Reaching task."""

    FORCE_MULTIPLIER = 0.05

    def __init__(self, distance_threshold=0.02, n_substeps=N_SUBSTEPS, relative_control=True,
                 initial_qpos=DEFAULT_INITIAL_QPOS, reward_type='dense', success_multiplier=0.1):
        self.success_multiplier = success_multiplier
        self.current_target_finger = "none"

        self._touch_sensor_id_site_id = []
        self._touch_sensor_id = []

        super().__init__(distance_threshold, n_substeps, relative_control, initial_qpos, reward_type)

        for k, v in self.sim.model._sensor_name2id.items():
            if 'robot0:TS_' in k:
                self._touch_sensor_id_site_id.append(
                    (v, self.sim.model._site_name2id[k.replace('robot0:TS_', 'robot0:T_')]))
                self._touch_sensor_id.append(v)

    def compute_reward(self, achieved_goal, goal, info):
        """Compute reward with additional success bonus."""
        return (super().compute_reward(achieved_goal, goal, info)
                + info["is_success"] * self.success_multiplier
                - self._get_force_punishment() * ShadowHandReach.FORCE_MULTIPLIER
        )

    def _get_force_punishment(self):
        # sum of squares, ignoring wrist (first two)
        sum_of_squared_forces = (self.sim.data.actuator_force[2:] ** 2).sum()
        return sum_of_squared_forces

    def _get_obs(self):
        # proprioception
        robot_qpos, robot_qvel = robot_get_obs(self.sim)

        # touch sensor information
        touch = self.sim.data.sensordata[self._touch_sensor_id]

        achieved_goal = self._get_achieved_goal().ravel()
        observation = np.concatenate([robot_qpos, robot_qvel, touch, achieved_goal, self.goal.copy()])

        return {
            'observation': observation.copy(),
            'achieved_goal': achieved_goal.copy(),
            'desired_goal': self.goal.copy(),
        }

    def _sample_goal(self):
        thumb_name = 'robot0:S_thtip'
        finger_names = [name for name in FINGERTIP_SITE_NAMES if name != thumb_name]
        finger_name = self.np_random.choice(finger_names)

        thumb_idx = FINGERTIP_SITE_NAMES.index(thumb_name)
        finger_idx = FINGERTIP_SITE_NAMES.index(finger_name)
        self.current_target_finger = finger_idx

        assert thumb_idx != finger_idx

        # Pick a meeting point above the hand.
        meeting_pos = self.palm_xpos + np.array([0.0, -0.09, 0.05])
        meeting_pos += self.np_random.normal(scale=0.005, size=meeting_pos.shape)

        # Slightly move meeting goal towards the respective finger to avoid that they overlap.
        goal = self.initial_goal.copy().reshape(-1, 3)
        for idx in [thumb_idx, finger_idx]:
            offset_direction = (meeting_pos - goal[idx])
            offset_direction /= np.linalg.norm(offset_direction)
            goal[idx] = meeting_pos - 0.005 * offset_direction

        if self.np_random.uniform() < 0.1:
            goal = self.initial_goal.copy()

        return goal.flatten()

    def step(self, action):
        """Step the environment."""
        o, r, d, i = super().step(action)
        i.update({"target_finger": self.current_target_finger})

        return o, r, d, i


class ShadowHandMultiReach(ShadowHandReach):
    """Reaching task where three fingers have to be joined."""

    def __init__(self, distance_threshold=0.02, n_substeps=N_SUBSTEPS, relative_control=True,
                 initial_qpos=DEFAULT_INITIAL_QPOS, reward_type='dense', success_multiplier=0.1):
        super().__init__(distance_threshold, n_substeps, relative_control, initial_qpos, reward_type,
                         success_multiplier)

    def _sample_goal(self):
        thumb_name = 'robot0:S_thtip'
        finger_names = [name for name in FINGERTIP_SITE_NAMES if name != thumb_name]

        # choose the fingers to join with the thumb
        finger_name_a, finger_name_b = self.np_random.choice(a=finger_names, size=2, replace=False)

        # retrieve their indices
        thumb_idx = FINGERTIP_SITE_NAMES.index(thumb_name)
        finger_idx_a = FINGERTIP_SITE_NAMES.index(finger_name_a)
        finger_idx_b = FINGERTIP_SITE_NAMES.index(finger_name_b)

        # pick a meeting point above the hand.
        meeting_pos = self.palm_xpos + np.array([0.0, -0.09, 0.05])
        meeting_pos += self.np_random.normal(scale=0.005, size=meeting_pos.shape)

        # Slightly move meeting goal towards the respective finger to avoid that they overlap.
        goal = self.initial_goal.copy().reshape(-1, 3)
        for idx in [thumb_idx, finger_idx_a, finger_idx_b]:
            offset_direction = (meeting_pos - goal[idx])
            offset_direction /= np.linalg.norm(offset_direction)
            goal[idx] = meeting_pos - 0.007 * offset_direction

        if self.np_random.uniform() < 0.1:
            # With some probability, ask all fingers to move back to the origin.
            # This avoids that the thumb constantly stays near the goal position already.
            goal = self.initial_goal.copy()

        return goal.flatten()


class ShadowHandFreeReach(ShadowHandReach):
    """Reaching task where the actual position of the joint fingers is irrelevant.

    It only matters which fingertips need to be joint. The reward is based on the distance between the fingertips,
    punishing distance of the thumb to target fingers and rewarding the distance to non-target fingers.

    The goal is represented as a one-hot vector of size 4."""

    def __init__(self, distance_threshold=0.02, n_substeps=N_SUBSTEPS, relative_control=True,
                 initial_qpos=DEFAULT_INITIAL_QPOS, success_multiplier=0.1, force_finger=None):
        assert force_finger in list(range(5)) + [None], "Forced finger index out of range [0, 5]."

        self.thumb_name = 'robot0:S_thtip'
        self.forced_finger = force_finger
        super().__init__(distance_threshold, n_substeps, relative_control, initial_qpos, "dense",
                         success_multiplier)

    def compute_reward(self, achieved_goal, goal, info):
        reward = (- get_fingertip_distance(self._get_thumb_position(), self._get_target_finger_position())
                  + info["is_success"] * self.success_multiplier
                  - self._get_force_punishment() * ShadowHandReach.FORCE_MULTIPLIER
                  )

        for i, fname in enumerate(FINGERTIP_SITE_NAMES):
            if fname == self.thumb_name or i == np.where(self.goal == 1)[0].item():
                continue

            reward += 0.2 * get_fingertip_distance(self._get_thumb_position(), self._get_finger_position(fname))

        return reward

    def _sample_goal(self):
        if self.forced_finger is None:
            finger_names = [name for name in FINGERTIP_SITE_NAMES if name != self.thumb_name]

            # choose the finger to join with the thumb
            finger_name = self.np_random.choice(a=finger_names, size=1, replace=False)

            # get finger id
            f_id = FINGERTIP_SITE_NAMES.index(finger_name)
        else:
            f_id = self.forced_finger

        self.current_target_finger = f_id

        # make one hot encoding
        goal = np.zeros(len(FINGERTIP_SITE_NAMES))
        goal[f_id] = 1

        return goal

    def _get_thumb_position(self):
        return self.sim.data.get_site_xpos(self.thumb_name).flatten()

    def _get_target_finger_position(self):
        return self.sim.data.get_site_xpos(FINGERTIP_SITE_NAMES[np.where(self.goal == 1)[0].item()]).flatten()

    def _get_finger_position(self, finger_name):
        return self.sim.data.get_site_xpos(finger_name).flatten()

    def _is_success(self, achieved_goal, desired_goal):
        d = get_fingertip_distance(self._get_thumb_position(), self._get_target_finger_position())
        return (d < self.distance_threshold).astype(np.float32)

    def _render_callback(self):
        sites_offset = (self.sim.data.site_xpos - self.sim.model.site_pos).copy()

        # Visualize finger positions.
        achieved_goal = self._get_achieved_goal().reshape(5, 3)
        for finger_idx in range(5):
            site_name = 'finger{}'.format(finger_idx)
            site_id = self.sim.model.site_name2id(site_name)

            fname = FINGERTIP_SITE_NAMES[finger_idx]
            if not (fname == self.thumb_name or finger_idx == np.where(self.goal == 1)[0].item()):
                self.sim.model.site_rgba[site_id][-1] = 0
                continue

            self.sim.model.site_rgba[site_id][-1] = 0.2
            self.sim.model.site_pos[site_id] = achieved_goal[finger_idx] - sites_offset[site_id]

        self.sim.forward()


class ShadowHandFreeReachVisual(ShadowHandFreeReach):

    def __init__(self, distance_threshold=0.02, n_substeps=N_SUBSTEPS, relative_control=True,
                 initial_qpos=DEFAULT_INITIAL_QPOS, success_multiplier=0.1, force_finger=None):
        # init rendering [IMPORTANT]
        from mujoco_py import GlfwContext
        GlfwContext(offscreen=True)  # in newer version of gym use quiet=True to silence this

        self.total_steps = 0

        super().__init__(distance_threshold=distance_threshold, n_substeps=n_substeps,
                         relative_control=relative_control, initial_qpos=initial_qpos,
                         success_multiplier=success_multiplier, force_finger=force_finger)

        # set hand and background colors
        self.sim.model.mat_rgba[2] = np.array([16, 18, 35, 255]) / 255
        self.sim.model.mat_rgba[4] = np.array([104, 143, 71, 255]) / 255
        self.sim.model.geom_rgba[48] = np.array([0.5, 0.5, 0.5, 0])

        # get touch sensor site names and their ids
        self._touch_sensor_id_site_id = []
        self._touch_sensor_id = []
        for k, v in self.sim.model._sensor_name2id.items():
            if 'robot0:TS_' in k:
                self._touch_sensor_id_site_id.append(
                    (v, self.sim.model._site_name2id[k.replace('robot0:TS_', 'robot0:T_')]))
                self._touch_sensor_id.append(v)

    def _determine_observation_space(self):
        obs = self._get_obs()
        self.observation_space = spaces.Dict(dict(
            desired_goal=spaces.Box(-np.inf, np.inf, shape=obs['desired_goal'].shape, dtype='float32'),
            achieved_goal=spaces.Box(-np.inf, np.inf, shape=obs['achieved_goal'].shape, dtype='float32'),
            observation=spaces.Tuple((
                spaces.Box(-np.inf, np.inf, shape=obs["observation"][0].shape, dtype='float32'),  # visual
                spaces.Box(-np.inf, np.inf, shape=obs["observation"][1].shape, dtype='float32'),  # proprioception
                spaces.Box(-np.inf, np.inf, shape=obs["observation"][2].shape, dtype='float32'),  # touch sensors
                spaces.Box(-np.inf, np.inf, shape=obs["observation"][3].shape, dtype='float32'),  # goal
            ))
        ))

    def _get_obs(self):
        # "primary" information, either this is the visual frame or the object position and velocity
        achieved_goal = self._get_achieved_goal().ravel()
        visual = self.render(mode="rgb_array", height=VISION_WH, width=VISION_WH)

        # get proprioceptive information (positions of joints) and touch sensors
        robot_pos, robot_vel = manipulate.robot_get_obs(self.sim)
        proprioception = np.concatenate([robot_pos, robot_vel])
        touch = self.sim.data.sensordata[self._touch_sensor_id]

        return {
            "observation": np.array((visual.copy(), proprioception.copy(), touch.copy(), self.goal.ravel().copy())),
            "achieved_goal": achieved_goal.copy(),
            "desired_goal": self.goal.ravel().copy(),
        }


class ShadowHandFreeReachAction(ShadowHandFreeReach):

    def __init__(self, distance_threshold=0.02, n_substeps=20, relative_control=True,
                 initial_qpos=DEFAULT_INITIAL_QPOS, success_multiplier=0.1, force_finger=None):

        super().__init__(distance_threshold, n_substeps, relative_control, initial_qpos,
                         success_multiplier, force_finger)
        self.previous_reward = 0

    def compute_reward(self, achieved_goal, goal, info):
        d = get_fingertip_distance(self._get_thumb_position(), self._get_target_finger_position())
        reward = -d + info["is_success"] * self.success_multiplier

        for i, fname in enumerate(FINGERTIP_SITE_NAMES):
            if fname == self.thumb_name or i == np.where(self.goal == 1)[0].item():
                continue

            reward += 0.2 * get_fingertip_distance(self._get_thumb_position(), self._get_finger_position(fname))

        reward_ratio_great = (reward / self.previous_reward - 1) > 0.1 * self.previous_reward
        if reward_ratio_great:
            reward = reward + 0.2 * (1 - reward / self.previous_reward)
        self.previous_reward = reward
        return reward


class ShadowHandTappingSequence(ShadowHandFreeReach):
    """Task in which a sequence of reaching movements needs to be performed.

    It only matters which fingertips need to be joint. The reward is based on the distance between the fingertips,
    punishing distance of the thumb to target fingers and rewarding the distance to non-target fingers."""

    def __init__(self, distance_threshold=0.02, n_substeps=N_SUBSTEPS, relative_control=True,
                 initial_qpos=DEFAULT_INITIAL_QPOS, success_multiplier=0.5):
        super().__init__(distance_threshold, n_substeps, relative_control, initial_qpos, success_multiplier)
        self.goal_sequence = [0, 1, 2, 3, 2, 1, 0]
        self.current_sequence_position = 0

    def compute_reward(self, achieved_goal, goal, info):
        current_goal_finger_id = self.goal_sequence[self.current_sequence_position]
        last_goal_finger_id = self.goal_sequence[0]
        if self.current_sequence_position > 0:
            last_goal_finger_id = self.goal_sequence[self.current_sequence_position - 1]

        current_goal_finger_name = FINGERTIP_SITE_NAMES[current_goal_finger_id]

        d = get_fingertip_distance(self._get_thumb_position(), self._get_finger_position(current_goal_finger_name))
        reward = -d + info["is_success"] * self.success_multiplier

        # incentivise distance to non target fingers
        for i, fname in enumerate(FINGERTIP_SITE_NAMES):
            # do not reward distance to self, thumb and last target (to give time to move away last target)
            if fname == self.thumb_name or i == current_goal_finger_id or i == last_goal_finger_id:
                continue

            reward += 0.2 * get_fingertip_distance(self._get_thumb_position(), self._get_finger_position(fname))

        reward -= 0.1  # constant punishment

        return reward

    def _sample_goal(self):
        return np.array([])

    def _get_thumb_position(self):
        return self.sim.data.get_site_xpos(self.thumb_name).flatten()

    def _get_target_finger_position(self):
        return self.sim.data.get_site_xpos(FINGERTIP_SITE_NAMES[np.where(self.goal == 1)[0].item()]).flatten()

    def _get_finger_position(self, finger_name):
        return self.sim.data.get_site_xpos(finger_name).flatten()

    def _is_success(self, achieved_goal, desired_goal):
        current_goal_finger_id = self.goal_sequence[self.current_sequence_position]
        current_goal_finger_name = FINGERTIP_SITE_NAMES[current_goal_finger_id]

        d = get_fingertip_distance(self._get_thumb_position(), self._get_finger_position(current_goal_finger_name))
        return (d < self.distance_threshold).astype(np.float32)

    def step(self, action):
        observation, reward, done, info = super().step(action)

        # set next goal
        if info["is_success"]:
            self.current_sequence_position += 1

        if self.current_sequence_position >= len(self.goal_sequence):
            done = True

        # sequence position cannot go above length of sequence
        self.current_sequence_position = min(self.current_sequence_position, len(self.goal_sequence) - 1)

        return observation, reward, done, info

    def reset(self):
        ret = super().reset()
        self.current_sequence_position = 0

        return ret

    def _render_callback(self):
        sites_offset = (self.sim.data.site_xpos - self.sim.model.site_pos).copy()

        # Visualize finger positions.
        achieved_goal = self._get_achieved_goal().reshape(5, 3)
        for finger_idx in range(5):
            fname = FINGERTIP_SITE_NAMES[finger_idx]
            site_name = 'finger{}'.format(finger_idx)
            site_id = self.sim.model.site_name2id(site_name)
            if not (fname == self.thumb_name or finger_idx == self.goal_sequence[self.current_sequence_position]):
                self.sim.model.site_rgba[site_id][-1] = 0
                continue

            self.sim.model.site_rgba[site_id][-1] = 0.2
            self.sim.model.site_pos[site_id] = achieved_goal[finger_idx] - sites_offset[site_id]

        self.sim.forward()


class ShadowHandDelayedTappingSequence(ShadowHandTappingSequence):
    """Task in which a sequence of reaching movements needs to be performed but on each finger the agent
    should rest some time.

    It only matters which fingertips need to be joint. The reward is based on the distance between the fingertips,
    punishing distance of the thumb to target fingers and rewarding the distance to non-target fingers."""

    def __init__(self, distance_threshold=0.02, n_substeps=N_SUBSTEPS, relative_control=True,
                 initial_qpos=DEFAULT_INITIAL_QPOS, success_multiplier=0.1, resting_duration=10):
        super().__init__(distance_threshold, n_substeps, relative_control, initial_qpos, success_multiplier)
        self.resting_duration = resting_duration
        self.steps_on_target = 0

    def step(self, action):
        observation, reward, done, info = HandReachEnv.step(self, action)

        # set next goal
        if info["is_success"]:
            # check if still in resting period
            if self.steps_on_target < self.resting_duration:
                self.steps_on_target += 1
            else:
                # if not in resting period, go to next sequence element and reset
                self.current_sequence_position += 1
                self.steps_on_target = 0

        if self.current_sequence_position >= len(self.goal_sequence):
            done = True

        # sequence position cannot go above length of sequence
        self.current_sequence_position = min(self.current_sequence_position, len(self.goal_sequence) - 1)

        return observation, reward, done, info


class ShadowHandBlockVector(HandBlockEnv):

    def _get_obs(self):
        robot_qpos, robot_qvel = robot_get_obs(self.sim)
        object_qvel = self.sim.data.get_joint_qvel('object:joint')
        achieved_goal = self._get_achieved_goal().ravel()  # this contains the object position + rotation
        observation = np.concatenate([robot_qpos, robot_qvel, object_qvel, achieved_goal, self.goal.ravel().copy()])

        return {
            'observation': observation.copy(),
            'achieved_goal': achieved_goal.copy(),
            'desired_goal': self.goal.ravel().copy(),
        }


if __name__ == "__main__":
    from environments import *

    # env = gym.make("HandTappingAbsolute-v1")
    # env = gym.make("HandFreeReachLFAbsolute-v0")
    # env = gym.make("ShadowHand-v0")
    # env = gym.make("HandManipulateBlock-v0")
    env = gym.make("HandReachDenseRelative-v0")
    d, s = False, env.reset()
    while True:
        env.render()
        action = env.action_space.sample()
        s, r, d, i = env.step(action)
        if d:
            env.reset()
