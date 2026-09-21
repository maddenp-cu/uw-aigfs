from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from aigfs import setup
from iotaa import Asset, collection, external, task
from uwtools.api.utils import run_shell_cmd

DIR = Path("/run/aigfs")
CMD = f"podman run -v .:{DIR} ghcr.io/maddenp-cu/aigfs:latest run cmd"

type C = datetime | str

# Public tasks:


@task
def config(c: C) -> Iterator:
    c = _dt(c)
    name = "Cycle %s config" % c
    yield name
    path = Path("aigfs.yaml")
    yield Asset(path, path.is_file)
    yield None
    config = setup.compose_configs(workflow=None, platform="oci", user_config_files=[f"{DIR}/user.yaml"])
    print(config)
    # cmd = [f"{CMD} setup", "--platform oci", f"{DIR}/user.yaml"]
    # run_shell_cmd(" ".join(cmd), taskname=name)


@collection
def cycle(cyclestr: str) -> Iterator:
    c = _dt(cyclestr)
    yield "Cycle %s" % _dt(c)
    yield post()


@task
def forecast(c: C) -> Iterator:
    c = _dt(c)
    yield "Cycle %s forecast" % c
    path = Path("forecast")
    Asset(path, path.is_file)
    yield prep(c)
    path.touch()


@task
def post(c: C) -> Iterator:
    c = _dt(c)
    yield "Cycle %s post" % c
    path = Path("post")
    yield Asset(path, path.is_file)
    yield forecast(c)
    path.touch()


@task
def prep(c: C) -> Iterator:
    c = _dt(c)
    name = "Cycle %s prep" % c
    yield name
    path = Path("prep/aigfs.t00z.ic.nc")
    yield Asset(path, path.is_file)
    yield [_timegate(c), config(c)]
    cmd = [
        f"{CMD} uw execute",
        "--module aigfs.drivers.ics",
        "--classname AIGFSICs",
        "--task run",
        f"--config {DIR}/aigfs.yaml",
        "--cycle %s" % c.isoformat(),
        "--key-path prep",
    ]
    run_shell_cmd(" ".join(cmd), taskname=name)


# Private tasks:


@external
def _timegate(c: datetime) -> Iterator:
    offset = timedelta(hours=3, minutes=35)
    cutoff = c + offset
    yield from [
        "UTC > %s" % cutoff.replace(tzinfo=None),
        Asset(None, lambda: datetime.now(UTC) > cutoff),
    ]


# Private helpers:


def _dt(c: C) -> datetime:
    if isinstance(c, str):
        return datetime.fromisoformat(c).replace(tzinfo=timezone.utc)
    return c
