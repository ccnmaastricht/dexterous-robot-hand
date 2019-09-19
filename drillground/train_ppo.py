import os

import tensorflow as tf

from agent.gathering import EpisodicGatherer, ContinuousGatherer
from agent.ppo import PPOAgentDual
from configs.env import CONFIG
from environments import *

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# activate eager execution to get rid of bullshit static graphs
tf.compat.v1.enable_eager_execution()
tf.keras.backend.set_floatx("float64")  # prevent precision issues

# ENVIRONMENT
# env = gym.make("LunarLander-v2")
env = gym.make("CartPole-v0")
# env = gym.make("Acrobot-v1")
# env = gym.make("Pendulum-v0")
# env = gym.make("TunnelRAM-v0")

setting_id = "BEST"

number_of_actions = env.action_space.n
state_dimensionality = env.observation_space.shape[0]
env_name = env.spec._env_name

print(env_name)
print(f"{state_dimensionality}-dimensional states and {number_of_actions} actions.")

# AGENT
gatherer = ContinuousGatherer(
    env,
    n_trajectories=CONFIG["PPO"][env_name][setting_id]["AGENTS"],
    T=200
)
agent = PPOAgentDual(state_dimensionality,
                     number_of_actions,
                     gatherer,
                     learning_rate=CONFIG["PPO"][env_name][setting_id]["LEARNING_RATE"],
                     discount=CONFIG["PPO"][env_name][setting_id]["DISCOUNT_FACTOR"],
                     epsilon_clip=CONFIG["PPO"][env_name][setting_id]["EPSILON_CLIP"])

agent.set_gpu(False)
agent.drill(env=env,
            iterations=CONFIG["PPO"][env_name][setting_id]["ITERATIONS"],
            epochs=CONFIG["PPO"][env_name][setting_id]["EPOCHS"],
            batch_size=CONFIG["PPO"][env_name][setting_id]["BATCH_SIZE"])

env.close()
