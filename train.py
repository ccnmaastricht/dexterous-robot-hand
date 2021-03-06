import argparse
import logging

import argcomplete
from gym.spaces import Box

import configs
from agent.policies import get_distribution_by_short_name
from agent.ppo import PPOAgent
from models import *
from models import get_model_builder
from models.shadow import build_blind_shadow_brain_v1
from utilities.const import COLORS
from utilities.monitoring import Monitor
from utilities.util import env_extract_dims
from utilities.wrappers import CombiWrapper, StateNormalizationWrapper, SkipWrapper, RewardNormalizationWrapper


class InconsistentArgumentError(Exception):
    """Arguments given to a process were inconsistent."""
    pass


def run_experiment(environment, settings: dict, verbose=True, init_ray=True, use_monitor=False) -> PPOAgent:
    """Run an experiment with the given settings ."""

    # sanity checks and warnings for given parameters
    if settings["preload"] is not None and settings["load_from"] is not None:
        raise InconsistentArgumentError("You gave both a loading from a pretrained component and from another "
                                        "agent state. This cannot be resolved.")

    # setup environment and extract and report information
    env = gym.make(environment)
    state_dim, number_of_actions = env_extract_dims(env)
    env_action_space_type = "continuous" if isinstance(env.action_space, Box) else "discrete"
    env_observation_space_type = "continuous" if isinstance(env.observation_space, Box) else "discrete"
    env_name = env.unwrapped.spec.id

    if env.spec.max_episode_steps is not None and env.spec.max_episode_steps > settings["horizon"] and not settings[
        "eval"]:
        logging.warning("Careful! Your horizon is lower than the max reward, this will most likely skew stats heavily.")

    # choose and make policy distribution
    if settings["distribution"] is None:
        settings["distribution"] = "categorical" if env_action_space_type == "discrete" else "gaussian"

    distribution = get_distribution_by_short_name(settings["distribution"])(env)

    # setting appropriate model building function
    if "ShadowHand" in environment or settings["architecture"] == "shadow":
        if settings["model"] == "ffn":
            print("Cannot use ffn with shadow architecture. Defaulting to GRU.")
            settings["model"] = "gru"

        if env.visual_input:
            build_models = get_model_builder(model="shadow", model_type=settings["model"], shared=settings["shared"])
        else:
            build_models = build_blind_shadow_brain_v1
    else:
        build_models = get_model_builder(model=settings["architecture"], model_type=settings["model"],
                                         shared=settings["shared"])

    # make preprocessor
    preprocessor = CombiWrapper(
        [StateNormalizationWrapper(state_dim) if not settings["no_state_norming"] else SkipWrapper(),
         RewardNormalizationWrapper() if not settings["no_reward_norming"] else SkipWrapper()])

    # announce experiment
    bc, ec, wn = COLORS["HEADER"], COLORS["ENDC"], COLORS["WARNING"]
    if verbose:
        print(f"-----------------------------------------\n"
              f"{wn}Learning the Task{ec}: {bc}{env_name}{ec}\n"
              f"{bc}{state_dim}{ec}-dimensional states ({bc}{env_observation_space_type}{ec}) "
              f"and {bc}{number_of_actions}{ec} actions ({bc}{env_action_space_type}{ec}).\n"
              f"Config: {settings['config']}\n"
              f"Model: {build_models.__name__}\n"
              f"Distribution: {settings['distribution']}\n"
              f"-----------------------------------------\n")

        print(f"{wn}HyperParameters{ec}: {settings}\n")

    if settings["cpu"]:
        os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

    if settings["load_from"] is not None:
        if verbose:
            print(f"{wn}Loading{ec} from state {settings['load_from']}")
        agent = PPOAgent.from_agent_state(settings["load_from"])
    else:
        # set up the agent and a reporting module
        agent = PPOAgent(build_models, env, horizon=settings["horizon"], workers=settings["workers"],
                         learning_rate=settings["lr_pi"], lr_schedule=settings["lr_schedule"],
                         discount=settings["discount"],
                         clip=settings["clip"], c_entropy=settings["c_entropy"], c_value=settings["c_value"],
                         lam=settings["lam"],
                         gradient_clipping=settings["grad_norm"], clip_values=settings["clip_values"],
                         tbptt_length=settings["tbptt"], distribution=distribution, preprocessor=preprocessor,
                         pretrained_components=None if settings["preload"] is None else [settings["preload"]],
                         debug=settings["debug"])

        print(f"{wn}Created agent{ec} with ID {bc}{agent.agent_id}{ec}")

    if tf.test.is_gpu_available():
        agent.set_gpu(not settings["cpu"])
    else:
        agent.set_gpu(False)

    monitor = None
    if use_monitor:
        monitor = Monitor(agent, env, frequency=settings["monitor_frequency"], gif_every=settings["gif_every"],
                      iterations=settings["iterations"], config_name=settings["config"])

    redis_auth = None if settings["redis_ip"] is None else [settings["redis_ip"], settings["redis_pw"]]
    agent.drill(n=settings["iterations"], epochs=settings["epochs"], batch_size=settings["batch_size"], monitor=monitor,
                export=settings["export_file"], save_every=settings["save_every"], separate_eval=settings["eval"],
                stop_early=settings["stop_early"], parallel=not settings["sequential"], ray_is_initialized=not init_ray,
                radical_evaluation=settings["radical_evaluation"], redis_auth=redis_auth)

    agent.save_agent_state()
    env.close()

    return agent


if __name__ == "__main__":
    os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

    all_envs = [e.id for e in list(gym.envs.registry.all())]

    # parse commandline arguments
    parser = argparse.ArgumentParser(description="Train a PPO Agent on some task.")

    # general parameters
    parser.add_argument("env", nargs='?', type=str, default="ShadowHandBlind-v0", choices=all_envs,
                        help="the target environment")
    parser.add_argument("--architecture", choices=["simple", "deeper", "shadow"], default="simple",
                        help="architecture of the policy")
    parser.add_argument("--model", choices=["ffn", "rnn", "lstm", "gru"], default="ffn",
                        help=f"model type if not shadowhand")
    parser.add_argument("--distribution", type=str, default=None, choices=["categorical", "gaussian", "beta"])
    parser.add_argument("--shared", action="store_true",
                        help=f"make the model share part of the network for policy and value")
    parser.add_argument("--iterations", type=int, default=1000, help=f"number of iterations before training ends")

    # meta arguments
    parser.add_argument("--config", type=str, default=None, help="config name (utilities/configs.py) to be loaded")
    parser.add_argument("--cpu", action="store_true", help=f"use cpu only")
    parser.add_argument("--sequential", action="store_true", help=f"run worker sequentially workers")
    parser.add_argument("--load-from", type=int, default=None, help=f"load from given agent id")
    parser.add_argument("--preload", type=str, default=None, help=f"load visual component weights from pretraining")
    parser.add_argument("--export-file", type=int, default=None, help=f"save policy to be loaded in workers into file")
    parser.add_argument("--eval", action="store_true", help=f"evaluate additionally to have at least 5 eps")
    parser.add_argument("--radical-evaluation", action="store_true", help=f"only record stats from seperate evaluation")
    parser.add_argument("--save-every", type=int, default=0, help=f"save agent every given number of iterations")
    parser.add_argument("--monitor-frequency", type=int, default=1, help=f"update the monitor every n iterations.")
    parser.add_argument("--gif-every", type=int, default=0, help=f"make a gif every n iterations.")
    parser.add_argument("--debug", action="store_true", help=f"run in debug mode")
    parser.add_argument("--redis-ip", type=str, help=f"redis head ip address", default=None)
    parser.add_argument("--redis-pw", type=str, help=f"redis password", default=None)

    # gathering parameters
    parser.add_argument("--workers", type=int, default=8, help=f"the number of workers exploring the environment")
    parser.add_argument("--horizon", type=int, default=2048, help=f"number of timesteps one worker generates")
    parser.add_argument("--discount", type=float, default=0.99, help=f"discount factor for future rewards")
    parser.add_argument("--lam", type=float, default=0.97, help=f"lambda parameter in the GAE algorithm")
    parser.add_argument("--no-state-norming", action="store_true", help=f"do not normalize states")
    parser.add_argument("--no-reward-norming", action="store_true", help=f"do not normalize rewards")

    # optimization parameters
    parser.add_argument("--epochs", type=int, default=3, help=f"the number of optimization epochs in each cycle")
    parser.add_argument("--batch-size", type=int, default=64, help=f"minibatch size during optimization")
    parser.add_argument("--lr-pi", type=float, default=1e-3, help=f"learning rate of the policy")
    parser.add_argument("--lr-schedule", type=str, default=None, choices=[None, "exponential"],
                        help=f"lr schedule type")
    parser.add_argument("--clip", type=float, default=0.2, help=f"clipping range around 1 for the objective function")
    parser.add_argument("--c-entropy", type=float, default=0.01, help=f"entropy factor in objective function")
    parser.add_argument("--c-value", type=float, default=1, help=f"value factor in objective function")
    parser.add_argument("--tbptt", type=int, default=16, help=f"length of subsequences in truncated BPTT")
    parser.add_argument("--grad-norm", type=float, default=0.5, help=f"norm for gradient clipping, 0 deactivates")
    parser.add_argument("--clip-values", action="store_true", help=f"clip value objective")
    parser.add_argument("--stop-early", action="store_true", help=f"stop early if threshold of env was surpassed")

    # read arguments
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    # if config is given load it as default, then overwrite with any other given parameters
    if args.config is not None:
        try:
            parser.set_defaults(**getattr(configs, args.config))
            args = parser.parse_args()
            print(f"Loaded Config {args.config}.")
        except AttributeError as err:
            raise ImportError("Cannot find config under given name. Does it exist in utilities/configs.py?")

    if args.debug:
        tf.config.experimental_run_functions_eagerly(True)
        logging.warning("YOU ARE RUNNING IN DEBUG MODE!")

    run_experiment(args.env, vars(args), use_monitor=True)
