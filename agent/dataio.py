#!/usr/bin/env python
"""Data reading and writing utilities for distributed learning."""
import os
import random

import tensorflow as tf

from utilities.const import STORAGE_DIR
from utilities.datatypes import ExperienceBuffer, StatBundle, TimeSequenceExperienceBuffer

if __name__ == "__main__":
    pass


def _float_feature(value):
    """Returns a float_list from a float / double."""
    return tf.train.Feature(float_list=tf.train.FloatList(value=[value]))


def _bytes_feature(value):
    """"Returns a bytes_list from a string / byte."""
    if isinstance(value, type(tf.constant(0))):
        value = value.numpy()
    return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))


def serialize_flat_sample(s, a, ap, r, adv, v):
    """Serialize a sample from a dataset."""
    feature = {
        "state": _bytes_feature(tf.io.serialize_tensor(s)),
        "action": _bytes_feature(tf.io.serialize_tensor(a)),
        "action_prob": _bytes_feature(tf.io.serialize_tensor(ap)),
        "return": _bytes_feature(tf.io.serialize_tensor(r)),
        "advantage": _bytes_feature(tf.io.serialize_tensor(adv)),
        "value": _bytes_feature(tf.io.serialize_tensor(v))
    }

    # Create a Features message using tf.train.Example.
    example_proto = tf.train.Example(features=tf.train.Features(feature=feature))
    return example_proto.SerializeToString()


def serialize_shadow_hand_sample(sv, sp, st, sg, a, ap, r, adv, v):
    """Serialize a multi-input (shadow hand) sample from a dataset."""
    feature = {
        "in_vision": _bytes_feature(tf.io.serialize_tensor(sv)),
        "in_proprio": _bytes_feature(tf.io.serialize_tensor(sp)),
        "in_touch": _bytes_feature(tf.io.serialize_tensor(st)),
        "in_goal": _bytes_feature(tf.io.serialize_tensor(sg)),
        "action": _bytes_feature(tf.io.serialize_tensor(a)),
        "action_prob": _bytes_feature(tf.io.serialize_tensor(ap)),
        "return": _bytes_feature(tf.io.serialize_tensor(r)),
        "advantage": _bytes_feature(tf.io.serialize_tensor(adv)),
        "value": _bytes_feature(tf.io.serialize_tensor(v))
    }

    # Create a Features message using tf.train.Example.
    example_proto = tf.train.Example(features=tf.train.Features(feature=feature))
    return example_proto.SerializeToString()


def tf_serialize_example(sample):
    """TF wrapper for serialization function."""
    if "state" in sample:
        inputs = (sample["state"],)
        serializer = serialize_flat_sample
    else:
        inputs = (sample["in_vision"], sample["in_proprio"], sample["in_touch"], sample["in_goal"])
        serializer = serialize_shadow_hand_sample
    inputs += (sample["action"], sample["action_prob"], sample["return"], sample["advantage"], sample["value"])

    tf_string = tf.py_function(serializer, inputs, tf.string)
    return tf.reshape(tf_string, ())


def make_dataset_and_stats(buffer: ExperienceBuffer, is_shadow_brain: bool):
    """Make dataset object and StatBundle from ExperienceBuffer."""
    completed_episodes = buffer.episodes_completed
    numb_processed_frames = buffer.capacity

    # expand dims when constructing dataset to inject batch dimension
    if is_shadow_brain:
        dataset = tf.data.Dataset.from_tensor_slices({
            "in_vision": buffer.states[0],
            "in_proprio": buffer.states[1],
            "in_touch": buffer.states[2],
            "in_goal": buffer.states[3],
            "action": buffer.actions,
            "action_prob": buffer.action_probabilities,
            "return": buffer.returns,
            "advantage": buffer.advantages,
            "value": buffer.advantages,
        })
    else:
        dataset = tf.data.Dataset.from_tensor_slices({
            "state": buffer.states,
            "action": buffer.actions,
            "action_prob": buffer.action_probabilities,
            "return": buffer.returns,
            "advantage": buffer.advantages,
            "value": buffer.advantages,
        })

    underflow = None
    if isinstance(buffer, TimeSequenceExperienceBuffer):
        underflow = round(1 - buffer.true_number_of_transitions / buffer.capacity, 2)

    stats = StatBundle(
        completed_episodes,
        numb_processed_frames,
        buffer.episode_rewards,
        buffer.episode_lengths,
        tbptt_underflow=underflow
    )

    return dataset, stats


def read_dataset_from_storage(dtype_actions: tf.dtypes.DType, is_shadow_hand: bool, shuffle: bool = True):
    """Read all files in storage into a tf record dataset without actually loading everything into memory."""
    feature_description = {
        "action": tf.io.FixedLenFeature([], tf.string),
        "action_prob": tf.io.FixedLenFeature([], tf.string),
        "return": tf.io.FixedLenFeature([], tf.string),
        "advantage": tf.io.FixedLenFeature([], tf.string),
        "value": tf.io.FixedLenFeature([], tf.string)
    }

    # add states
    if not is_shadow_hand:
        feature_description["state"] = tf.io.FixedLenFeature([], tf.string)
    else:
        feature_description.update({
            "in_vision": tf.io.FixedLenFeature([], tf.string),
            "in_proprio": tf.io.FixedLenFeature([], tf.string),
            "in_touch": tf.io.FixedLenFeature([], tf.string),
            "in_goal": tf.io.FixedLenFeature([], tf.string),
        })

    def _parse_function(example_proto):
        # Parse the input `tf.Example` proto using the dictionary above.
        parsed = tf.io.parse_single_example(example_proto, feature_description)
        if not is_shadow_hand:
            parsed["state"] = tf.io.parse_tensor(parsed["state"], out_type=tf.float32)
        else:
            parsed["in_vision"] = tf.io.parse_tensor(parsed["in_vision"], out_type=tf.float32)
            parsed["in_proprio"] = tf.io.parse_tensor(parsed["in_proprio"], out_type=tf.float32)
            parsed["in_touch"] = tf.io.parse_tensor(parsed["in_touch"], out_type=tf.float32)
            parsed["in_goal"] = tf.io.parse_tensor(parsed["in_goal"], out_type=tf.float32)
        parsed["action"] = tf.io.parse_tensor(parsed["action"], out_type=dtype_actions)
        parsed["action_prob"] = tf.io.parse_tensor(parsed["action_prob"], out_type=tf.float32)
        parsed["return"] = tf.io.parse_tensor(parsed["return"], out_type=tf.float32)
        parsed["advantage"] = tf.io.parse_tensor(parsed["advantage"], out_type=tf.float32)
        parsed["value"] = tf.io.parse_tensor(parsed["value"], out_type=tf.float32)

        return parsed

    files = [os.path.join(STORAGE_DIR, name) for name in os.listdir(STORAGE_DIR)]
    if shuffle:
        random.shuffle(files)
    serialized_dataset = tf.data.TFRecordDataset(files)
    serialized_dataset = serialized_dataset.map(_parse_function)

    return serialized_dataset
