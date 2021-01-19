import os
import sys
import matplotlib.pyplot as plt

from analysis.chiefinvestigation import Chiefinvestigator
import sklearn.decomposition as skld
from analysis.rnn_dynamical_systems.fixedpointfinder.FixedPointFinder import Adamfixedpointfinder
from analysis.rnn_dynamical_systems.fixedpointfinder.plot_utils import plot_fixed_points, plot_velocities

os.chdir("../../")  # remove if you want to search for ids in the analysis directory
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

agent_id = 1588341681 # halfcheetah

chiefinvesti = Chiefinvestigator(agent_id)

layer_names = chiefinvesti.get_layer_names()
print(layer_names)

# collect data from episodes
n_episodes = 5
activations_over_all_episodes, inputs_over_all_episodes, actions_over_all_episodes, states_all_episodes, info = \
    chiefinvesti.get_data_over_episodes(n_episodes, "policy_recurrent_layer", layer_names[1])

adamfpf = Adamfixedpointfinder(chiefinvesti.weights, chiefinvesti.rnn_type)


x, y, z, u, v, w = chiefinvesti.compute_quiver_data(inputs_over_all_episodes, activations_over_all_episodes,
                                                    3, 5)

n_points = 300

pca = skld.PCA(3)
pca.fit(activations_over_all_episodes)
X_pca = pca.transform(activations_over_all_episodes)

fig = plt.figure()
ax = fig.add_subplot(projection='3d')
ax.plot(X_pca[:n_points, 0], X_pca[:n_points, 1], X_pca[:n_points, 2],
        linewidth=0.7)
ax.quiver(x, y, z, u, v, w, color = 'g', length=0.4)
ax.set_xlabel('PC1')
ax.set_ylabel('PC2')
ax.set_zlabel('PC3')
plt.show()

# velocities = adamfpf.compute_velocities(activations_over_all_episodes, inputs_over_all_episodes)
# plot_velocities(actions_over_all_episodes, velocities,500)