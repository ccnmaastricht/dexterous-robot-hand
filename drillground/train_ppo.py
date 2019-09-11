import os

import gym
import tensorflow as tf

from agent.policy_gradient import ActorCriticREINFORCEAgent, PPOAgent

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# activate eager execution to get rid of bullshit static graphs
tf.compat.v1.enable_eager_execution()
tf.keras.backend.set_floatx("float64")  # prevent precision issues

# ENVIRONMENT
env = gym.make("CartPole-v0")
number_of_actions = env.action_space.n
state_dimensionality = env.observation_space.shape[0]

print(env.spec._env_name)
print(f"{state_dimensionality}-dimensional states and {number_of_actions} actions.")

# AGENT
agent = PPOAgent(state_dimensionality, number_of_actions)
agent.drill(env, 1000, 32)

env.close()
