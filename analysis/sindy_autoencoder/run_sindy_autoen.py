import os
import numpy as np
import jax.numpy as jnp
import matplotlib.pyplot as plt
from analysis.chiefinvestigation import Chiefinvestigator
from analysis.sindy_autoencoder.sindy_autoencoder import SindyAutoencoder

os.chdir("../../")  # remove if you want to search for ids in the analysis directory
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# agent_id = 1607352660  # cartpole-v1
agent_id = 1607352660 # inverted pendulum no vel, continuous action
# agent_id = 1586597938# finger tapping

chiefinvesti = Chiefinvestigator(agent_id)

layer_names = chiefinvesti.get_layer_names()
print(layer_names)

# collect data from episodes
n_episodes = 500
activations_over_all_episodes, inputs_over_all_episodes, actions_over_all_episodes, states_all_episodes, done \
    = chiefinvesti.get_data_over_episodes(n_episodes, "policy_recurrent_layer", layer_names[1])
print(f"SIMULATED {n_episodes} episodes")

dx = np.gradient(activations_over_all_episodes, axis=0)

training_data = {'x': activations_over_all_episodes,
                 'dx': dx}

layers = [64, 32, 8, 4]
seed = 1
SA = SindyAutoencoder(layers, poly_order=2, seed=seed, max_epochs=5000,
                      refinement_epochs=1000)

SA.train(training_data=training_data)
SA.save_state(filename='InvPendulum')
#SA.load_state(filename='CartPoleSindy')

#a = chiefinvesti.sub_model_to.predict(np.reshape(np.array([1, 0, 0, 0]), (1, 1, 4)))

fig, ax = plt.subplots()
plt.spy(SA.coefficient_mask * SA.autoencoder['sindy_coefficients'],
        marker='o', markersize=10)
labels = ['z1', 'z2', 'z3', 'z4']
#plt.axis('off')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['bottom'].set_visible(False)
plt.xticks([0, 1, 2, 3], labels)
plt.show()

all_train_losses = {k: [dic[k] for dic in SA.all_train_losses] for k in SA.all_train_losses[0]}
for key in all_train_losses:
    if key != 'total' and key != 'recon':
        plt.plot(np.asarray(jnp.vstack(all_train_losses[key])), label=key)
plt.legend()
plt.show()
