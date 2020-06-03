import os
import sys
import matplotlib.pyplot as plt
import numpy as np

from analysis.chiefinvestigation import Chiefinvestigator
from analysis.rnn_dynamical_systems.fixedpointfinder.FixedPointFinder import Adamfixedpointfinder
from analysis.rnn_dynamical_systems.fixedpointfinder.plot_utils import plot_fixed_points, plot_velocities
from time import sleep
# example script to analyse the smallstepreach agent
os.chdir("../../")  # remove if you want to search for ids in the analysis directory
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

agent_id, env = 1588151579, 'HandFreeReachRFAbsolute-v0' # small step reach task

chiefinvesti = Chiefinvestigator(agent_id, env, from_iteration='best')

layer_names = chiefinvesti.get_layer_names()
print(layer_names)

# collect data from episodes
n_episodes = 5
activations_over_all_episodes, inputs_over_all_episodes, actions_over_all_episodes, states_all_episodes, done = \
    chiefinvesti.get_data_over_episodes(n_episodes, "policy_recurrent_layer", layer_names[1])

plt.plot(activations_over_all_episodes[:1000, :], linewidth=0.3)
plt.xlabel('Timesteps')
plt.ylabel('Activation')
plt.show()


# employ fixedpointfinder
adamfpf = Adamfixedpointfinder(chiefinvesti.weights, chiefinvesti.rnn_type,
                               q_threshold=1e-14,
                               tol_unique=2e-03,
                               epsilon=5e-03)

states, inputs = adamfpf.sample_inputs_and_states(activations_over_all_episodes, inputs_over_all_episodes,
                                                  100, 0)
fps = adamfpf.find_fixed_points(states, inputs)

plot_fixed_points(activations_over_all_episodes, fps, 200, 1)
plt.show()

#for fp in fps:
#    chiefinvesti.render_fixed_points(np.repeat(np.reshape(fp['x'], (1, 1, 32)), axis=1, repeats=100))
#    sleep(3)
velocities = adamfpf.compute_velocities(activations_over_all_episodes, inputs_over_all_episodes)

plot_velocities(activations_over_all_episodes, velocities)