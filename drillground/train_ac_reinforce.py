import os

import gym

from agent.policy_gradient import ActorCriticREINFORCEAgent

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
import tensorflow as tf

# activate eager execution to get rid of bullshit static graphs
tf.compat.v1.enable_eager_execution()
tf.keras.backend.set_floatx("float64")  # prevent precision issues

# SETTINGS
TOTAL_EPISODES = 100000

# ENVIRONMENT
env = gym.make("CartPole-v0")
number_of_actions = env.action_space.n
state_dimensionality = env.observation_space.shape[0]

print(env.spec._env_name)
print(f"{state_dimensionality}-dimensional states and {number_of_actions} actions.")

# AGENT
agent = ActorCriticREINFORCEAgent(state_dimensionality, number_of_actions)
agent.drill(env, TOTAL_EPISODES)

env.close()
