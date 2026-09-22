import inspect
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import FrameType
from typing import cast

from aigfs import setup
from aigfs.drivers.ics import AIGFSICs
from iotaa import Asset, collection, external, task

# DIR = Path("/run/aigfs")
DIR = Path("/home/maddenp/git/uw-aigfs")
CMD = f"podman run -v .:{DIR} ghcr.io/maddenp-cu/aigfs:latest run cmd"

type CycleT = datetime | str

# Public tasks:


@task
def config(cycle_: CycleT) -> Iterator:
    cycle_ = _dt(cycle_)
    name = "Cycle %s config" % cycle_
    yield name
    path = Path(DIR / "aigfs.yaml")
    yield Asset(path, path.is_file)
    yield None
    user = Path(f"{DIR}/user.yaml")
    config = setup.compose_configs(workflow=None, platform="oci", user_config_files=[user])
    setup.validate(config)
    setup.set_up_rundir(config, workflow=None, prefix=name)


@collection
def cycle(cyclestr: str) -> Iterator:
    cycle_ = _dt(cyclestr)
    yield "Cycle %s" % _dt(cycle_)
    yield post()


@task
def forecast(cycle_: CycleT) -> Iterator:
    cycle_ = _dt(cycle_)
    yield "Cycle %s forecast" % cycle_
    path = Path("forecast")
    Asset(path, path.is_file)
    yield prep(cycle_)
    path.touch()


@task
def post(cycle_: CycleT) -> Iterator:
    cycle_ = _dt(cycle_)
    yield "Cycle %s post" % cycle_
    path = Path("post")
    yield Asset(path, path.is_file)
    yield forecast(cycle_)
    path.touch()


@task
def prep(cycle_: CycleT) -> Iterator:
    cycle_ = _dt(cycle_)
    step = cast(FrameType, inspect.currentframe()).f_code.co_name
    name = "Cycle %s %s" % (cycle_, step)
    yield name
    fn = "aigfs.t%sz.ic.nc" % _hh(cycle_)
    path = _cycledir(cycle_) / step / fn
    yield Asset(path, path.is_file)
    config_ = config(cycle_)
    yield [_timegate(cycle_), config_]
    driver = AIGFSICs(
        cycle=cycle_, config=config_.ref, key_path=[step], schema_file=_schema(AIGFSICs)
    )
    driver.run()


# Private tasks:


@external
def _timegate(cycle_: datetime) -> Iterator:
    offset = timedelta(hours=3, minutes=35)
    cutoff = cycle_ + offset
    yield from [
        "UTC > %s" % cutoff.replace(tzinfo=None),
        Asset(None, lambda: datetime.now(UTC) > cutoff),
    ]


# Private helpers:


def _cycledir(cycle_: datetime) -> Path:
    return Path(cycle_.strftime("%Y%m%d"), _hh(cycle_))


def _dt(cycle_: CycleT) -> datetime:
    if isinstance(cycle_, str):
        return datetime.fromisoformat(cycle_).replace(tzinfo=timezone.utc)
    return cycle_


def _hh(cycle_: datetime) -> str:
    return cycle_.strftime("%H")


def _schema(class_: type) -> Path:
    return Path(inspect.getfile(class_)).with_suffix(".jsonschema")
