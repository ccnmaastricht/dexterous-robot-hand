from jax import vmap, random, jit, value_and_grad, jacobian
import jax.numpy as jnp
import jax
from jax.experimental import optimizers
import time
import pickle
import os

from analysis.sindy_autoencoder.utils import library_size, control_autoencoder_pass, build_sindy_control_autoencoder, \
    encoding_pass, sindy_library_jax


class SindyControlAutoencoder(object):

    def __init__(self, layer_sizes: list, poly_order: int,
                 seed: int = 1,
                 sequential_thresholding: bool = True,
                 coefficient_threshold: float = 0.1,
                 threshold_frequency: int = 500,
                 use_sine: bool = False,
                 recon_loss_weight: float = 1.0,
                 sindy_z_loss_weight: float = 0.0,
                 sindy_x_loss_weight: float = 1e-4,
                 sindy_u_loss_weight: float = 1e-4,
                 sindy_regularization_loss_weight: float = 1e-5,
                 control_recon_loss_weight: float = 1.0,
                 max_epochs: int = 5000,
                 refinement_epochs: int = 1000,
                 batch_size: int = 8000,
                 learning_rate: float = 1e-3,
                 print_updates: bool = True):
        self.layer_sizes = layer_sizes
        self.poly_order = poly_order
        self.library_size = library_size(layer_sizes[-1], poly_order, use_sine=use_sine, include_control=True)

        self.key = random.PRNGKey(seed)
        self.autoencoder, self.coefficient_mask = build_sindy_control_autoencoder(layer_sizes,
                                                                                  self.library_size,
                                                                                  self.key)
        self.vmap_autoencoder_pass = vmap(control_autoencoder_pass, in_axes=({'encoder': None,
                                                                              'decoder': None,
                                                                              'control_encoder': None,
                                                                              'control_decoder': None,
                                                                              'sindy_coefficients': None},
                                                                             None, 0, 0, 0, 0))

        self.recon_loss_weight = recon_loss_weight
        self.sindy_z_loss_weight = sindy_z_loss_weight
        self.sindy_x_loss_weight = sindy_x_loss_weight
        self.sindy_regularization_loss_weight = sindy_regularization_loss_weight
        self.sindy_u_loss_weight = sindy_u_loss_weight
        self.control_recon_loss_weight = control_recon_loss_weight

        self.loss_jit = jit(self.loss, device=jax.devices()[0])
        self.jit_update = jit(self.update, device=jax.devices()[0])

        # optimizer
        self.learning_rate = learning_rate
        self.opt_init, self.opt_update, self.get_params = optimizers.adam(learning_rate)
        self.max_epochs = max_epochs
        self.refinement_epochs = refinement_epochs
        self.batch_size = batch_size

        # thresholding for coefficient mask
        self.sequential_thresholding = sequential_thresholding
        self.thresholding_frequency = threshold_frequency
        self.coefficient_threshold = coefficient_threshold

        self.print_updates = print_updates

        self.train_loss = []
        self.all_train_losses = []
        self.refinement_loss = []

    def loss(self, sindy_autoencoder, coefficient_mask, x, dx, u, du):
        [x, dx, dz, u, du, x_decode, dx_decode, u_decode, du_decode, sindy_predict] = self.vmap_autoencoder_pass(sindy_autoencoder,
                                                                                   coefficient_mask,
                                                                                   x,
                                                                                   dx,
                                                                                   u,
                                                                                   du)

        reconstruction_loss = jnp.mean((x - x_decode) ** 2)
        control_reconstruction_loss = jnp.mean((u - u_decode) ** 2)
        sindy_u = jnp.mean((du - du_decode) ** 2)
        #sindy_z = jnp.mean((dz - sindy_predict) ** 2)
        sindy_x = jnp.mean((dx - dx_decode) ** 2)
        sindy_regularization = jnp.mean(jnp.abs(sindy_autoencoder['sindy_coefficients']))

        reconstruction_loss = self.recon_loss_weight * reconstruction_loss
        #sindy_z_loss = self.sindy_z_loss_weight * sindy_z
        sindy_x_loss = self.sindy_x_loss_weight * sindy_x
        sindy_regularization_loss = self.sindy_regularization_loss_weight * sindy_regularization
        control_recon_loss = self.control_recon_loss_weight * control_reconstruction_loss
        sindy_u_loss = self.sindy_u_loss_weight * sindy_u

        total_loss = reconstruction_loss + sindy_x_loss + sindy_regularization_loss \
                     + control_recon_loss + sindy_u_loss
        return {'total': total_loss,
                'recon': reconstruction_loss,
                #'sindy_z': sindy_z_loss,
                'sindy_x': sindy_x_loss,
                'sindy_l2': sindy_regularization_loss,
                'control_recon': control_recon_loss,
                'sindy_u': sindy_u_loss}

    def training_loss(self, sindy_autoencoder, coefficient_mask, x, dx, u, du):
        return self.loss(sindy_autoencoder, coefficient_mask, x, dx, u, du)['total']

    def update(self, params, coefficient_mask, X, dx, u, du, opt_state):
        value, grads = value_and_grad(self.training_loss)(params, coefficient_mask, X, dx, u, du)
        opt_state = self.opt_update(0, grads, opt_state)
        return self.get_params(opt_state), opt_state, value

    def train(self, training_data: dict):
        n_updates = 0

        opt_state = self.opt_init(self.autoencoder)
        params = self.get_params(opt_state)

        num_batches = int(jnp.ceil(len(training_data['x']) / self.batch_size))
        batch_size = self.batch_size

        def batch_indices(iter):
            idx = iter % num_batches
            return slice(idx * batch_size, (idx + 1) * batch_size)
        print("TRAINING...")
        for epoch in range(self.max_epochs):
            start = time.time()
            for i in range(num_batches):
                id = batch_indices(i)

                params, opt_state, value = self.jit_update(params, self.coefficient_mask,
                                                           training_data['x'][id, :],
                                                           training_data['dx'][id, :],
                                                           training_data['u'][id, :],
                                                           training_data['du'][id, :],
                                                           opt_state)

                n_updates += 1

            if epoch % self.thresholding_frequency == 0 and epoch > 1 and self.sequential_thresholding:
                self.coefficient_mask = jnp.abs(params['sindy_coefficients']) > 0.1
                print("Updated coefficient mask")

            # record
            losses = self.loss_jit(params, self.coefficient_mask,
                                   training_data['x'][id, :],
                                   training_data['dx'][id, :],
                                   training_data['u'][id, :],
                                   training_data['du'][id, :])
            self.train_loss.append(losses['total'])
            self.all_train_losses.append(losses)

            stop = time.time()
            dt = stop - start
            if self.print_updates:
                self.print_update(epoch, n_updates, dt)

        print("REFINEMENT...")
        self.sindy_regularization_loss_weight = 0.0  # no regularization anymore

        for ref_epoch in range(self.refinement_epochs):
            start = time.time()
            for i in range(num_batches):
                id = batch_indices(i)

                params, opt_state, value = self.jit_update(params, self.coefficient_mask,
                                                           training_data['x'][id, :],
                                                           training_data['dx'][id, :],
                                                           training_data['u'][id, :],
                                                           training_data['du'][id, :],
                                                           opt_state)

                n_updates += 1

            # record
            losses = self.loss_jit(params, self.coefficient_mask,
                                   training_data['x'][id, :],
                                   training_data['dx'][id, :],
                                   training_data['u'][id, :],
                                   training_data['du'][id, :])

            self.refinement_loss.append(losses['total'])
            self.all_train_losses.append(losses)
            stop = time.time()
            dt = stop - start
            if self.print_updates:
                self.print_update(ref_epoch, n_updates, dt)

        print(f"FINISHING...\n"
              f"Sparsity: {jnp.sum(self.coefficient_mask)} active terms")

        self.autoencoder = params

    def validate(self):
        pass

    def save_state(self, filename, save_dir: str = ''):
        state = {'autoencoder': self.autoencoder,
                 'coefficient_mask': self.coefficient_mask,
                 'hps': {'layers': self.layer_sizes,
                         'poly_order': self.poly_order,
                         'library:size': self.library_size,
                         'lr': self.learning_rate,
                         'epochs': self.max_epochs,
                         'batch_size': self.batch_size,
                         'sequential_threshold': self.sequential_thresholding,
                         'thresholding_frequency': self.thresholding_frequency,
                         'threshold_coefficient': self.coefficient_threshold},
                 'history': {'train_loss': self.train_loss,
                             'refinement_loss': self.refinement_loss}}

        try:
            directory = os.getcwd() + '/analysis/sindy_autoencoder/' + save_dir + filename + '.pkl'

            with open(file=directory, mode='wb') as f:
                pickle.dump(state, f, pickle.HIGHEST_PROTOCOL)

        except FileNotFoundError:
            directory = '/analysis/sindy_autoencoder/' + save_dir + filename + '.pkl'

            with open(file=directory, mode='wb') as f:
                pickle.dump(state, f, pickle.HIGHEST_PROTOCOL)

    def load_state(self, filename, save_dir: str = ''):
        try:
            directory = os.getcwd() + '/analysis/sindy_autoencoder/' + save_dir + filename + '.pkl'
            with open(directory, 'rb') as f:
                state = pickle.load(f)

        except FileNotFoundError:
            directory = '/analysis/sindy_autoencoder/' + save_dir + filename + '.pkl'
            with open(directory, 'rb') as f:
                state = pickle.load(f)

        self.autoencoder = state['autoencoder']
        self.coefficient_mask = state['coefficient_mask']
        self.layer_sizes = state['hps']['layers']
        self.poly_order = state['hps']['poly_order']
        self.library_size = state['hps']['library:size']
        self.learning_rate = state['hps']['lr']
        self.max_epochs = state['hps']['epochs']
        self.batch_size = state['hps']['batch_size']
        self.sequential_thresholding = state['hps']['sequential_threshold']
        self.thresholding_frequency = state['hps']['thresholding_frequency']
        self.coefficient_threshold = state['hps']['threshold_coefficient']
        self.train_loss = state['history']['train_loss']
        self.refinement_loss = state['history']['refinement_loss']

    def print_update(self, epoch, n_updates, dt):
        print(f"Epoch {1 + epoch}",
              f"| Loss {round(self.train_loss[-1], 7)}",
              f"| Updates {n_updates}",
              f"| This took: {round(dt, 4)}s")