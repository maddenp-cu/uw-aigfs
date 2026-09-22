from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from aigfs import setup
from iotaa import Asset, collection, external, task
from uwtools.api.utils import run_shell_cmd

DIR = Path("/run/aigfs")
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
    name = "Cycle %s prep" % cycle_
    yield name
    path = Path("prep/aigfs.t00z.ic.nc")
    yield Asset(path, path.is_file)
    config_ = config(cycle_)
    yield [_timegate(cycle_), config_]
    cmd = [
        f"{CMD} uw execute",
        "--module aigfs.drivers.ics",
        "--classname AIGFSICs",
        "--task run",
        f"--config {config_.ref}",
        "--cycle %s" % cycle_.isoformat(),
        "--key-path prep",
    ]
    run_shell_cmd(" ".join(cmd), taskname=name)


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


def _dt(cycle_: CycleT) -> datetime:
    if isinstance(cycle_, str):
        return datetime.fromisoformat(cycle_).replace(tzinfo=timezone.utc)
    return cycle_
