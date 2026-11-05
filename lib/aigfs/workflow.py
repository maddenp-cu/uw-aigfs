import fcntl
import inspect
import logging
import os
import re
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from shutil import rmtree
from typing import TypeVar

from iotaa import Asset, Node, collection, external, task
from pydantic import BaseModel, ConfigDict, PositiveInt
from uwtools.api.config import realize_to_dict
from uwtools.api.driver import Driver
from uwtools.api.logging import use_uwtools_logger
from uwtools.api.utils import run_shell_cmd

from aigfs import setup
from aigfs.drivers.ics import AIGFSICs
from aigfs.drivers.inference import AIGFSInference
from aigfs.drivers.post import AIGFSPost
from aigfs.strings import STR
from aigfs.validation import App as App_
from aigfs.validation import Config as Config_

APPDIR = Path(os.environ.get("APPDIR") or Path.cwd())
CONFIG = APPDIR / STR.aigfs_yaml

type CycleT = datetime | str

use_uwtools_logger()

# Validation classes:


class AppCycles(App_):
    cycle_freq: timedelta
    first_cycle: datetime
    last_cycle: datetime


class AppRealtime(App_):
    cycle_freq: timedelta


class User(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    window_prune: bool = False
    window_size: PositiveInt


class ConfigCycles(Config_):
    app: AppCycles
    user: User  # type: ignore[assignment]


class ConfigRealtime(Config_):
    app: AppRealtime
    user: User  # type: ignore[assignment]


ConfigT = TypeVar("ConfigT", ConfigCycles, ConfigRealtime)

# Public tasks:


@task
def config() -> Iterator:
    """
    The composed AIGFS config YAML file.
    """
    taskname = "config"
    yield taskname
    yield Asset(CONFIG, CONFIG.is_file)
    yield None
    user = APPDIR / "user.yaml"
    raw_config = setup.compose_configs(workflow=None, platform=STR.oci, user_config_files=[user])
    valid_config = setup.validate(raw_config)
    setup.set_up_rundir(valid_config, workflow=None, prefix=taskname)


@collection
def cycle(cycle_: CycleT) -> Iterator:
    """
    A complete prep > forecast > post execution for one cycle.
    """
    dt, taskname = _dt_taskname(cycle_, "cycle")
    yield taskname
    yield post(dt)


@collection
def cycles() -> Iterator:
    """
    Execution of all defined cycles.
    """

    # Process leading-edge cycles first.

    yield "cycles"
    app = _config(ConfigCycles).app
    dts = []
    dt, first = _utc(app.last_cycle), _utc(app.first_cycle)
    while dt >= first:
        dts.append(dt)
        dt -= app.cycle_freq
    yield [cycle(dt) for dt in dts]


@task
def forecast(cycle_: CycleT) -> Iterator:
    """
    Execution of the inference driver for one cycle.
    """
    dt, taskname = _dt_taskname(cycle_, STR.forecast)
    yield taskname
    cls = AIGFSInference
    key_path: list = [STR.forecast]
    driver = cls(cycle=dt, config=CONFIG, key_path=key_path, schema_file=_schema(cls))
    assets = [Asset(path, path.is_file) for path in driver.output[STR.forecast]]
    yield assets
    yield prep(dt)
    prefix = "srun --exclusive --nodes=1 --time=30"
    cmd = _cmd(driver, key_path, dt, prefix=prefix)
    _execute(cmd, driver.rundir, taskname, assets)


@collection
def post(cycle_: CycleT) -> Iterator:
    """
    Execution of the post driver for one cycle.
    """

    # Instantiate the inference driver and use its declared output to define the one-per-leadtime
    # post tasks required to post-process the full forecast cycle. Each leadtime involves two GRIB
    # files, one '.pres.' and one '.sfc.', so process them as per-leadtime pairs.

    dt, taskname = _dt_taskname(cycle_, STR.post)
    yield taskname
    cls = AIGFSInference
    inference = cls(cycle=dt, config=CONFIG, key_path=[STR.forecast], schema_file=_schema(cls))
    paths = iter(sorted(sorted(inference.output[STR.forecast]), key=_fff))
    yield [_post_one_leadtime(dt, pres, sfc) for pres, sfc in zip(paths, paths, strict=False)]


@task
def prep(cycle_: CycleT) -> Iterator:
    """
    Execution of the prep driver for one cycle.
    """
    dt, taskname = _dt_taskname(cycle_, STR.prep)
    yield taskname
    cls = AIGFSICs
    key_path: list = [STR.prep]
    driver = cls(cycle=dt, config=CONFIG, key_path=key_path, schema_file=_schema(cls))
    path = driver.output[STR.ics]
    assets = [Asset(path, path.is_file)]
    yield assets
    yield _timegate(dt)
    cmd = _cmd(driver, key_path, dt)
    _execute(cmd, driver.rundir, taskname, assets)


@collection
def realtime() -> Iterator:
    """
    Execution of a rolling realtime window of cycles.
    """

    # Process leading-edge cycles, latest first. Optionally remove trailing-edge cycle directories.

    c = _config(ConfigRealtime)
    yield f"{c.user.window_size} realtime cycles"
    ts = datetime.now(UTC).timestamp()
    n = c.user.window_size
    latest = datetime.fromtimestamp(ts - (ts % c.app.cycle_freq.total_seconds()), UTC)
    reqs: list[Node] = [_prune(Path(c.app.rundir), n)] if c.user.window_prune else []
    reqs.extend([cycle(latest - (n * c.app.cycle_freq)) for n in range(n)])
    yield reqs


# Private tasks:


@task
def _forecast_one_leadtime(dt: datetime, pres: Path, sfc: Path) -> Iterator:

    # This task models availability of a one-leadtime pres/sfc GRIB-file forecast pair. If the pair
    # is available, then the task is ready, the final yield is never reached, and the task requiring
    # this one can make use of its assets, the GRIB files. If the pair is not available, then the
    # forecast task is yielded as a requirement and executed, this task remains not ready during the
    # current invocation, and the task requiring this one is blocked. Note that this task has no
    # action code and could have been an @external task, except that the final yield is needed to
    # ensure that the forecast task runs.

    fff = _fff(pres)
    dt, taskname = _dt_taskname(dt, "%s %s" % (fff, STR.forecast))
    yield taskname
    yield [Asset(path, path.is_file) for path in (pres, sfc)]
    yield forecast(dt)


@task
def _post_one_leadtime(dt: datetime, pres: Path, sfc: Path) -> Iterator:

    # This task's assets are indexes in the delivery directory if delivery is enabled, and are
    # otherwise indexes in the original location where they were generated.

    fff = _fff(pres)
    dt, taskname = _dt_taskname(dt, "%s %s" % (fff, STR.post))
    yield taskname
    cls = AIGFSPost
    key_path: list = [STR.post]
    leadtime = timedelta(hours=int(fff))
    driver = cls(
        cycle=dt, leadtime=leadtime, config=CONFIG, key_path=key_path, schema_file=_schema(cls)
    )
    output = driver.output
    paths = output.get(STR.delivered, output[STR.idx])
    assets = [Asset(path, path.is_file) for path in paths]
    yield assets
    yield _forecast_one_leadtime(dt, pres, sfc)
    cmd = _cmd(driver, key_path, dt, leadtime)
    _execute(cmd, driver.rundir, taskname, assets)


@task
def _prune(rundir: Path, window_size: int) -> Iterator:

    # Remove trailing-edge cycle directories, keeping the newest window_size.

    def handler(_function: Callable, failed: str, exc: BaseException) -> None:
        logging.error("Could not remove %s: %s", failed, exc)

    def prunable() -> list[Path]:
        if not rundir.is_dir():
            return []
        is_cycledir = lambda path: path.is_dir() and re.match(r"^\d{10}$", path.name)
        return sorted(filter(is_cycledir, rundir.iterdir()))[:-window_size]

    yield "Prune cycle directories in %s" % rundir
    yield Asset(None, lambda: not prunable())
    yield None
    for path in prunable():
        logging.info("Pruning cycle directory %s", path)
        rmtree(path, onexc=handler)


@external
def _timegate(dt: datetime) -> Iterator:
    cutoff = _utc(dt) + timedelta(hours=3, minutes=35)
    yield "UTC > %s" % cutoff.replace(tzinfo=None)
    yield Asset(None, lambda: datetime.now(UTC) > cutoff)


# Private helpers:


def _cmd(
    driver: Driver,
    key_path: list,
    dt: datetime,
    leadtime: timedelta | None = None,
    prefix: str = "",
) -> str:
    cmd = [
        prefix,
        f"{APPDIR}/bin/run cmd",
        "uw execute",
        "--module %s" % driver.__module__,
        "--classname %s" % driver.__class__.__name__,
        "--task run",
        "--config %s" % CONFIG,
        "--key-path %s" % ".".join(key_path),
        "--cycle %s" % dt.strftime("%Y%m%dT%H"),
    ]
    if leadtime is not None:
        cmd.append("--leadtime %s" % int(leadtime.total_seconds() / 3600))
    return " ".join(cmd).strip()


@cache
def _config(model: type[ConfigT]) -> ConfigT:
    return model.model_validate(realize_to_dict(CONFIG))


def _dt_taskname(cycle_: CycleT, step: str) -> tuple[datetime, str]:
    dt = _utc(datetime.fromisoformat(cycle_) if isinstance(cycle_, str) else cycle_)
    return dt, "%s %s" % (dt.strftime("%Y%m%d %HZ"), step)


def _execute(cmd: str, rundir: Path, taskname: str, assets: list[Asset]) -> None:

    # flock (exclusive, non-blocking) on a per-task lockfile in the rundir so that one process at a
    # time runs a specific driver parameterization. The lock is released when the file is closed or
    # the process exits.

    def log(proc):
        logger = _passthrough_logger()
        for line in proc.stdout:
            logger.info(line.rstrip("\r\n"))

    rundir.mkdir(parents=True, exist_ok=True)
    lockfile = rundir / (".lock-%s" % taskname.replace(" ", "-"))
    with lockfile.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("%s: Running in another process", taskname)
            return
        if all(asset.ready() for asset in assets):
            logging.info("%s: Made ready by another process", taskname)
            return
        run_shell_cmd(cmd, callback=log, cwd=rundir, taskname=taskname)


def _fff(gribfile: Path) -> str:

    # e.g. aigfs.t00z.pres.f018.grib2
    #                       fff

    return gribfile.name.split(".")[3][1:]


def _passthrough_logger() -> logging.Logger:
    logger = logging.getLogger("passthrough")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = next((h for h in logger.handlers if isinstance(h, logging.StreamHandler)), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    handler.stream = sys.stderr
    return logger


def _schema(cls: type) -> Path:
    return Path(inspect.getfile(cls)).with_suffix(".jsonschema")


def _utc(dt: datetime) -> datetime:

    # Treat a naive datetime as UTC; convert an aware one to UTC.

    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
