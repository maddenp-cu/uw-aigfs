"""
Support for setting up AIGFS runtime assets.
"""

import argparse
import logging
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from uwtools.api import ecflow, rocoto
from uwtools.api.config import YAMLConfig, compose_to_dict
from uwtools.api.logging import use_uwtools_logger

from aigfs.common import ETCDIR, HOMEDIR, PLATFORMDIR, platforms
from aigfs.strings import STR
from aigfs.validation import validate


def compose_configs(workflow: str | None, platform: str, user_config_files: list[Path]) -> dict:
    """
    Compose and realize base, platform, and user configs.
    """
    if not workflow:
        logging.debug("No --workflow value supplied, omitting workflow support")
    with NamedTemporaryFile(delete=True) as tmp:
        p_base = ETCDIR / STR.base_yaml
        p_workflow = ETCDIR / STR.workflow / f"{workflow}.yaml" if workflow else None
        p_platform = PLATFORMDIR / f"{platform}.yaml"
        p_reserved = Path(tmp.name)
        app = {STR.app: {STR.home: str(HOMEDIR), STR.platform: {STR.name: platform}}}
        YAMLConfig(app).dump(p_reserved)
        configs = [x for x in [p_base, p_workflow, p_platform, *user_config_files, p_reserved] if x]
        return compose_to_dict(configs, realize=True)


def main() -> None:
    """
    Stage the AIGFS config and workflow manager artifacts in the run directory.
    """
    args = parse_args()
    use_uwtools_logger(verbose=args.verbose)
    config = compose_configs(args.workflow, args.platform, args.user_config_files)
    validate(config)
    set_up_rundir(config, args.workflow)


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Configure AIGFS.")
    parser.add_argument(
        "--platform",
        choices=platforms(),
        help="one of: %s" % ", ".join(platforms()),
        metavar="PLATFORM",
        required=True,
        type=str,
    )
    parser.add_argument(
        "--workflow",
        choices=["ecflow", "rocoto"],
        help="workflow manager",
        required=False,
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="enable verbose logging",
    )
    parser.add_argument(
        "user_config_files",
        help="path to user config file",
        metavar="PATH",
        nargs="+",
        type=Path,
    )
    return parser.parse_args()


def set_up_rundir(config: dict, workflow: str | None) -> None:
    """
    Create and populate the run directory.
    """
    rundir = Path(config[STR.app][STR.rundir])
    logging.info("AIGFS will be set up here: %s", rundir)
    rundir.mkdir(parents=True, exist_ok=True)
    final = rundir / STR.aigfs_yaml
    YAMLConfig(config).dump(final)
    if workflow == "ecflow":
        ecflow.realize(YAMLConfig(config), rundir, scripts_path=rundir / "ecf")
    elif workflow == "rocoto" and not rocoto.realize(YAMLConfig(config), rundir / STR.rocoto_xml):
        logging.error("Invalid Rocoto XML")
        sys.exit(1)


if __name__ == "__main__":
    main()  # pragma: no cover
