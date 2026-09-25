import inspect
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import FrameType
from typing import cast

from aigfs import setup
from aigfs.drivers.ics import AIGFSICs
from aigfs.drivers.inference import AIGFSInference
from iotaa import Asset, external, task

type CycleT = datetime | str

DIR = Path("/home/maddenp/git/uw-aigfs")  # /run/aigfs
CFG = DIR / "aigfs.yaml"
CMD = f"podman run -v .:{DIR} ghcr.io/maddenp-cu/aigfs:latest run cmd"

# Public tasks:


@task
def config(cycle_: CycleT) -> Iterator:
    step = cast(FrameType, inspect.currentframe()).f_code.co_name
    _, taskname = _dt_taskname(cycle_, step)
    yield taskname
    yield Asset(CFG, CFG.is_file)
    yield None
    user = DIR / "user.yaml"
    c = setup.compose_configs(workflow=None, platform="oci", user_config_files=[user])
    setup.validate(c)
    setup.set_up_rundir(c, workflow=None, prefix=taskname)


# @collection
# def cycle(cyclestr: str) -> Iterator:
#     cycle_ = _dt(cyclestr)
#     yield "Cycle %s" % _dt(cycle_)
#     yield post()


@task
def forecast(cycle_: CycleT) -> Iterator:
    step = cast(FrameType, inspect.currentframe()).f_code.co_name
    dt, taskname = _dt_taskname(cycle_, step)
    yield taskname
    class_ = AIGFSInference
    driver = class_(cycle=dt, config=CFG, key_path=[step], schema_file=_schema(class_))
    path = Path("foo")
    yield Asset(path, path.is_file)
    yield prep(dt)
    driver.run(iotaa={"root": True})


# @task
# def post(cycle_: CycleT) -> Iterator:
#     cycle_ = _dt(cycle_)
#     yield "Cycle %s post" % cycle_
#     path = Path("post")
#     yield Asset(path, path.is_file)
#     yield forecast(cycle_)
#     path.touch()


@task
def prep(cycle_: CycleT) -> Iterator:
    step = cast(FrameType, inspect.currentframe()).f_code.co_name
    dt, taskname = _dt_taskname(cycle_, step)
    yield taskname
    class_ = AIGFSICs
    driver = class_(cycle=dt, config=CFG, key_path=[step], schema_file=_schema(class_))
    path = driver.output["ics"]
    yield Asset(path, path.is_file)
    yield [_timegate(dt)]
    driver.run(iotaa={"root": True})


# Private tasks:


@external
def _timegate(cycle_: datetime) -> Iterator:
    cutoff = cycle_ + timedelta(hours=3, minutes=35)
    yield "UTC > %s" % cutoff.replace(tzinfo=None)
    yield Asset(None, lambda: datetime.now(UTC) > cutoff)


# Private helpers:


def _cycledir(cycle_: datetime) -> Path:
    return Path(cycle_.strftime("%Y%m%d%H"))


def _dt(cycle_: CycleT) -> datetime:
    if isinstance(cycle_, str):
        return datetime.fromisoformat(cycle_).replace(tzinfo=timezone.utc)
    return cycle_


def _dt_taskname(cycle_: CycleT, step: str) -> tuple[datetime, str]:
    cycle_ = _dt(cycle_)
    return cycle_, "%s %s" % (cycle_.strftime("%Y%m%d %HZ"), step)


def _schema(class_: type) -> Path:
    return Path(inspect.getfile(class_)).with_suffix(".jsonschema")
