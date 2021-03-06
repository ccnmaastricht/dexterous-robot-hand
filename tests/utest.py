import itertools
import logging
import os
import random
import unittest

import gym
import numpy as np
import ray
import tensorflow as tf
from scipy.signal import lfilter
from scipy.stats import norm, entropy, beta

from agent.core import extract_discrete_action_probabilities, estimate_advantage
from agent.policies import GaussianPolicyDistribution, CategoricalPolicyDistribution, BetaPolicyDistribution
from agent.ppo import PPOAgent
from analysis.investigation import Investigator
from models import get_model_builder
from utilities.const import NP_FLOAT_PREC
from utilities.model_utils import reset_states_masked
from utilities.util import insert_unknown_shape_dimensions
from utilities.wrappers import StateNormalizationWrapper, RewardNormalizationWrapper

from tests import *

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'


class CoreTest(unittest.TestCase):

    def test_extract_discrete_action_probabilities(self):
        # no recurrence
        action_probs = tf.convert_to_tensor([[1, 5], [3, 7], [7, 2], [8, 4], [0, 2], [4, 5], [4, 2], [7, 5]])
        actions = tf.convert_to_tensor([1, 0, 1, 1, 0, 0, 0, 1])
        result_reference = tf.convert_to_tensor([5, 3, 2, 4, 0, 4, 4, 5])
        result = extract_discrete_action_probabilities(action_probs, actions)

        self.assertTrue(tf.reduce_all(tf.equal(result, result_reference)).numpy().item())

    def test_extract_discrete_action_probabilities_with_recurrence(self):
        tf.config.experimental_run_functions_eagerly(True)

        # with recurrence
        action_probs = tf.convert_to_tensor(
            [[[1, 5], [1, 5]], [[3, 7], [3, 7]], [[7, 2], [7, 2]], [[8, 4], [8, 4]], [[0, 2], [0, 2]], [[4, 5], [4, 5]],
             [[4, 2], [4, 2]], [[7, 5], [7, 5]]])
        actions = tf.convert_to_tensor([[1, 1], [0, 0], [1, 1], [1, 1], [0, 0], [0, 0], [0, 0], [1, 1]])
        result_reference = tf.convert_to_tensor([[5, 5], [3, 3], [2, 2], [4, 4], [0, 0], [4, 4], [4, 4], [5, 5]])
        result = extract_discrete_action_probabilities(action_probs, actions)

        self.assertTrue(tf.reduce_all(tf.equal(result, result_reference)).numpy().item())


class ProbabilityTest(unittest.TestCase):

    # GAUSSIAN

    def test_gaussian_pdf(self):
        distro = GaussianPolicyDistribution(gym.make("LunarLanderContinuous-v2"))

        x = tf.convert_to_tensor([[2, 3], [4, 3], [2, 1]], dtype=tf.float32)
        mu = tf.convert_to_tensor([[2, 1], [1, 3], [2, 2]], dtype=tf.float32)
        sig = tf.convert_to_tensor([[2, 2], [1, 2], [2, 1]], dtype=tf.float32)

        result_reference = np.prod(norm.pdf(x, loc=mu, scale=sig), axis=-1)
        result_pdf = distro.probability(x, mu, sig).numpy()
        result_log_pdf = np.exp(distro.log_probability(x, mu, np.log(sig)).numpy())

        self.assertTrue(np.allclose(result_reference, result_pdf), msg="Gaussian PDF returns wrong Result")
        self.assertTrue(np.allclose(result_pdf, result_log_pdf), msg="Gaussian Log PDF returns wrong Result")

    def test_gaussian_entropy(self):
        distro = GaussianPolicyDistribution(gym.make("LunarLanderContinuous-v2"))

        mu = tf.convert_to_tensor([[2.0, 3.0], [2.0, 1.0]], dtype=tf.float32)
        sig = tf.convert_to_tensor([[1.0, 1.0], [1.0, 5.0]], dtype=tf.float32)

        result_reference = np.sum(norm.entropy(loc=mu, scale=sig), axis=-1)
        result_log = distro.entropy(np.log(sig)).numpy()
        result = distro._entropy_from_params(sig).numpy()

        self.assertTrue(np.allclose(result_reference, result), msg="Gaussian entropy returns wrong result")
        self.assertTrue(np.allclose(result_log, result_reference), msg="Gaussian entropy from log returns wrong result")

    # BETA

    def test_beta_pdf(self):
        distro = BetaPolicyDistribution(gym.make("LunarLanderContinuous-v2"))

        x = tf.convert_to_tensor([[0.2, 0.3], [0.4, 0.3], [0.2, 0.1]], dtype=tf.float32)
        alphas = tf.convert_to_tensor([[2, 1], [1, 3], [2, 2]], dtype=tf.float32)
        betas = tf.convert_to_tensor([[2, 2], [1, 2], [2, 1]], dtype=tf.float32)

        result_reference = np.prod(beta.pdf(distro._scale_sample_to_distribution_range(x), alphas, betas), axis=-1)
        result_pdf = distro.probability(x, alphas, betas).numpy()
        result_log_pdf = np.exp(distro.log_probability(x, alphas, betas).numpy())

        self.assertTrue(np.allclose(result_reference, result_log_pdf), msg="Beta Log PDF returns wrong Result")
        self.assertTrue(np.allclose(result_reference, result_pdf), msg="Beta PDF returns wrong Result")

    def test_beta_entropy(self):
        distro = BetaPolicyDistribution(gym.make("LunarLanderContinuous-v2"))

        alphas = tf.convert_to_tensor([[2, 1], [1, 3], [2, 2]], dtype=tf.float32)
        betas = tf.convert_to_tensor([[2, 2], [1, 2], [2, 1]], dtype=tf.float32)

        result_reference = np.sum(beta.entropy(alphas, betas), axis=-1)
        result_pdf = distro._entropy_from_params((alphas, betas)).numpy()

        self.assertTrue(np.allclose(result_reference, result_pdf), msg="Beta PDF returns wrong Result")

    # CATEGORICAL

    def test_categorical_entropy(self):
        distro = CategoricalPolicyDistribution(gym.make("CartPole-v1"))

        probs = tf.convert_to_tensor([[0.1, 0.4, 0.2, 0.25, 0.05],
                                      [0.1, 0.4, 0.2, 0.2, 0.1],
                                      [0.1, 0.35, 0.3, 0.24, 0.01]], dtype=tf.float32)

        result_reference = [entropy(probs[i]) for i in range(len(probs))]
        result_log = distro._entropy_from_log_pmf(np.log(probs)).numpy()
        result = distro._entropy_from_pmf(probs).numpy()

        self.assertTrue(np.allclose(result_reference, result), msg="Discrete entropy returns wrong result")
        self.assertTrue(np.allclose(result_log, result_reference), msg="Discrete entropy from log returns wrong result")


class UtilTest(unittest.TestCase):

    def test_masked_state_reset(self):
        model = tf.keras.Sequential((
            tf.keras.layers.Dense(2, batch_input_shape=(7, None, 2)),
            tf.keras.layers.LSTM(5, stateful=True, name="larry", return_sequences=True),
            tf.keras.layers.LSTM(5, stateful=True, name="harry"))
        )

        l_layer = model.get_layer("larry")
        h_layer = model.get_layer("harry")
        l_layer.reset_states([s.numpy() + 9 for s in l_layer.states])
        h_layer.reset_states([s.numpy() + 9 for s in h_layer.states])
        reset_states_masked(model, [True, False, False, True, False, False, True])

        self.assertTrue(np.allclose([s.numpy() for s in model.get_layer("larry").states],
                                    [s.numpy() for s in model.get_layer("harry").states]))
        self.assertTrue(np.allclose([s.numpy() for s in model.get_layer("larry").states], [
            [0, 0, 0, 0, 0],
            [9, 9, 9, 9, 9],
            [9, 9, 9, 9, 9],
            [0, 0, 0, 0, 0],
            [9, 9, 9, 9, 9],
            [9, 9, 9, 9, 9],
            [0, 0, 0, 0, 0],
        ]))


class WrapperTest(unittest.TestCase):

    def test_state_normalization(self):
        normalizer = StateNormalizationWrapper(10)

        inputs = [tf.random.normal([10]) for _ in range(15)]
        true_mean = np.mean(inputs, axis=0)
        true_std = np.std(inputs, axis=0)

        for sample in inputs:
            o, _, _, _ = normalizer.modulate((sample, 1, 1, 1))

        self.assertTrue(np.allclose(true_mean, normalizer.mean))
        self.assertTrue(np.allclose(true_std, np.sqrt(normalizer.variance)))

    def test_reward_normalization(self):
        normalizer = RewardNormalizationWrapper()

        inputs = [random.random() * 10 for _ in range(1000)]
        true_mean = np.mean(inputs, axis=0)
        true_std = np.std(inputs, axis=0)

        for sample in inputs:
            o, _, _, _ = normalizer.modulate((1, sample, 1, 1))

        self.assertTrue(np.allclose(true_mean, normalizer.mean))
        self.assertTrue(np.allclose(true_std, np.sqrt(normalizer.variance)))

    def test_state_normalization_adding(self):
        normalizer_a = StateNormalizationWrapper(10)
        normalizer_b = StateNormalizationWrapper(10)
        normalizer_c = StateNormalizationWrapper(10)

        inputs_a = [tf.random.normal([10], dtype=NP_FLOAT_PREC) for _ in range(10)]
        inputs_b = [tf.random.normal([10], dtype=NP_FLOAT_PREC) for _ in range(10)]
        inputs_c = [tf.random.normal([10], dtype=NP_FLOAT_PREC) for _ in range(10)]

        true_mean = np.mean(inputs_a + inputs_b + inputs_c, axis=0)
        true_std = np.std(inputs_a + inputs_b + inputs_c, axis=0)

        for sample in inputs_a:
            normalizer_a.update(sample)

        for sample in inputs_b:
            normalizer_b.update(sample)

        for sample in inputs_c:
            normalizer_c.update(sample)

        combined_normalizer = normalizer_a + normalizer_b + normalizer_c

        self.assertTrue(np.allclose(true_mean, combined_normalizer.mean))
        self.assertTrue(np.allclose(true_std, np.sqrt(combined_normalizer.variance)))

    def test_reward_normalization_adding(self):
        normalizer_a = RewardNormalizationWrapper()
        normalizer_b = RewardNormalizationWrapper()
        normalizer_c = RewardNormalizationWrapper()

        inputs_a = [random.random() * 10 for _ in range(1000)]
        inputs_b = [random.random() * 20 for _ in range(1000)]
        inputs_c = [random.random() * 5 for _ in range(1000)]

        true_mean = np.mean(inputs_a + inputs_b + inputs_c, axis=0)
        true_std = np.std(inputs_a + inputs_b + inputs_c, axis=0)

        for sample in inputs_a:
            normalizer_a.update(sample)

        for sample in inputs_b:
            normalizer_b.update(sample)

        for sample in inputs_c:
            normalizer_c.update(sample)

        combined_normalizer = normalizer_a + normalizer_b + normalizer_c

        self.assertTrue(np.allclose(true_mean, combined_normalizer.mean))
        self.assertTrue(np.allclose(true_std, np.sqrt(combined_normalizer.variance)))


if __name__ == '__main__':
    tf.config.experimental_run_functions_eagerly(True)

    testsuite = unittest.TestLoader().discover('.')
    unittest.TextTestRunner(verbosity=1).run(testsuite)