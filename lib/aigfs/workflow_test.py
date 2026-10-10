import fcntl
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import ANY, Mock, patch

from iotaa import Asset
from pytest import fixture, mark

from aigfs import workflow
from aigfs.drivers.inference import AIGFSInference
from aigfs.strings import STR

# Fixtures


@fixture
def cfg(tmp_path):
    path = tmp_path / "aigfs.yaml"
    with patch.object(workflow, "CONFIG", path), patch.object(workflow, "APPDIR", tmp_path):
        yield path


@fixture
def cycle(utc):
    return utc(2025, 10, 1, 18)


@fixture
def gribfiles(tmp_path):
    return [
        tmp_path / ("aigfs.t18z.%s.f%03d.grib2" % (kind, hour))
        for hour in (6, 12)
        for kind in (STR.pres, STR.sfc)
    ]


@fixture
def lockkit(tmp_path):
    rundir = tmp_path / "run"
    output = tmp_path / "out"
    obj = Mock(rundir=rundir)
    obj.run.side_effect = lambda *_, **_k: output.touch()
    assets = [Asset(output, output.is_file)]
    return obj, assets, rundir / ".lock-20251001-18Z-012-post", output


TASKNAME = "20251001 18Z 012 post"


def driver(output: dict, rundir: Path) -> Mock:
    obj = Mock(output=output, rundir=rundir)
    return Mock(return_value=obj)


# Tests


def test_workflow_config__exists(cfg, touch):
    touch(cfg)
    with patch.object(workflow, "setup") as setup:
        node = workflow.config()
    assert node.ready
    assert node.taskname == "config"
    setup.compose_configs.assert_not_called()


@mark.usefixtures("cfg")
def test_workflow_config__missing(tmp_path):
    with patch.object(workflow, "setup") as setup:
        node = workflow.config()
    assert not node.ready
    setup.compose_configs.assert_called_once_with(
        workflow=None, platform="oci", user_config_files=[tmp_path / "user.yaml"]
    )
    c = setup.compose_configs.return_value
    setup.validate.assert_called_once_with(c)
    setup.set_up_rundir.assert_called_once_with(c, workflow=None, prefix="config")


@mark.parametrize("ready", [True, False])
def test_workflow_cycle(atask, cycle, ready):
    with patch.object(workflow, STR.post, Mock(wraps=lambda _: atask(ready))) as post:
        node = workflow.cycle(cycle)
    assert node.ready is ready
    assert node.taskname == "20251001 18Z cycle"
    post.assert_called_once_with(cycle)


@mark.parametrize("ready", [True, False])
def test_workflow_cycles(atask, cycle, ready):
    app = {
        "first_cycle": cycle,
        "last_cycle": cycle + timedelta(hours=12),
        "cycle_freq": timedelta(hours=6),
    }
    with (
        patch.object(workflow, "_config", return_value={"app": app}),
        patch.object(workflow, "cycle", Mock(wraps=lambda _: atask(ready))) as cycle_,
    ):
        node = workflow.cycles()
    assert node.ready is ready
    assert node.taskname == "cycles"
    assert [c.args for c in cycle_.call_args_list] == [
        (cycle + timedelta(hours=12),),  # leading-edge first
        (cycle + timedelta(hours=6),),
        (cycle,),
    ]


@mark.parametrize("ready", [True, False])
def test_workflow_forecast(atask, cfg, cycle, gribfiles, ready, tmp_path):
    cls = driver({STR.forecast: gribfiles}, tmp_path / "run")
    with (
        patch.object(workflow, "AIGFSInference", cls),
        patch.object(workflow, "_schema", return_value=Path("/s")),
        patch.object(workflow, "prep", Mock(wraps=lambda _: atask(ready))) as prep,
        patch.object(workflow, "run_shell_cmd") as run_shell_cmd,
    ):
        if ready:
            run_shell_cmd.side_effect = lambda *_, **_k: [
                gribfile.touch() for gribfile in gribfiles
            ]
        node = workflow.forecast(cycle)
    assert node.taskname == "20251001 18Z forecast"
    cls.assert_called_once_with(
        cycle=cycle, config=cfg, key_path=[STR.forecast], schema_file=Path("/s")
    )
    prep.assert_called_once_with(cycle)
    assert node.ready is ready
    if ready:
        run_shell_cmd.assert_called_once_with(
            ANY, callback=ANY, cwd=cls.return_value.rundir, taskname="20251001 18Z forecast"
        )
    else:
        run_shell_cmd.assert_not_called()


@mark.parametrize("ready", [True, False])
def test_workflow_post(atask, cfg, cycle, gribfiles, ready, tmp_path):
    cls = driver({STR.forecast: gribfiles}, tmp_path / "run")
    with (
        patch.object(workflow, "AIGFSInference", cls),
        patch.object(workflow, "_schema", return_value=Path("/s")),
        patch.object(
            workflow, "_post_one_leadtime", Mock(wraps=lambda *_: atask(ready=ready))
        ) as _post_one_leadtime,
    ):
        node = workflow.post(cycle)
    assert node.ready is ready
    assert node.taskname == "20251001 18Z post"
    cls.assert_called_once_with(
        cycle=cycle, config=cfg, key_path=[STR.forecast], schema_file=Path("/s")
    )
    for pres, sfc in zip(gribfiles[::2], gribfiles[1::2], strict=True):
        _post_one_leadtime.assert_any_call(cycle, pres, sfc)


@mark.parametrize("ready", [True, False])
def test_workflow_prep(atask, cfg, cycle, ready, tmp_path):
    ics = tmp_path / "ics.nc"
    cls = driver({"ics": ics}, tmp_path / "run")
    with (
        patch.object(workflow, "AIGFSICs", cls),
        patch.object(workflow, "_schema", return_value=Path("/s")),
        patch.object(workflow, "_timegate", Mock(wraps=lambda _: atask(ready))) as _timegate,
        patch.object(workflow, "run_shell_cmd") as run_shell_cmd,
    ):
        if ready:
            run_shell_cmd.side_effect = lambda *_, **_k: ics.touch()
        node = workflow.prep(cycle)
    assert node.taskname == "20251001 18Z prep"
    cls.assert_called_once_with(
        cycle=cycle, config=cfg, key_path=[STR.prep], schema_file=Path("/s")
    )
    _timegate.assert_called_once_with(cycle)
    assert node.ready is ready
    if ready:
        run_shell_cmd.assert_called_once_with(
            ANY, callback=ANY, cwd=cls.return_value.rundir, taskname="20251001 18Z prep"
        )
    else:
        run_shell_cmd.assert_not_called()


@mark.parametrize("ready", [True, False])
def test_workflow__forecast_one_leadtime(atask, cycle, gribfiles, ready, touch):
    pres, sfc = gribfiles[:2]
    if ready:
        touch(pres)
        touch(sfc)
    with patch.object(workflow, STR.forecast, Mock(wraps=lambda _: atask(ready=True))) as forecast:
        node = workflow._forecast_one_leadtime(cycle, pres, sfc)
    assert node.taskname == "20251001 18Z 006 forecast"
    assert node.ready is ready
    forecast.assert_called_once_with(cycle)


@mark.parametrize("deliver", [True, False])
@mark.parametrize("ready", [True, False])
def test_workflow__post_one_leadtime(atask, cfg, cycle, deliver, gribfiles, ready, tmp_path):
    pres, sfc = gribfiles[2:]
    names = [f"{x.name}.idx" for x in (pres, sfc)]
    output = {STR.idx: [tmp_path / STR.post / x for x in names]}
    if deliver:
        output[STR.delivered] = [tmp_path / "delivery" / x for x in names]
    expected = output[STR.delivered] if deliver else output[STR.idx]
    for x in expected:
        x.parent.mkdir(parents=True, exist_ok=True)
    cls = driver(output, tmp_path / "run")
    with (
        patch.object(workflow, "AIGFSPost", cls),
        patch.object(workflow, "_schema", return_value=Path("/s")),
        patch.object(
            workflow, "_forecast_one_leadtime", Mock(wraps=lambda *_: atask(ready))
        ) as _forecast_one_leadtime,
        patch.object(workflow, "run_shell_cmd") as run_shell_cmd,
    ):
        if ready:
            run_shell_cmd.side_effect = lambda *_, **_k: [x.touch() for x in expected]
        node = workflow._post_one_leadtime(cycle, pres, sfc)
    assert node.taskname == "20251001 18Z 012 post"
    _forecast_one_leadtime.assert_called_once_with(cycle, pres, sfc)
    assert node.ready is ready
    cls.assert_called_once_with(
        cycle=cycle,
        leadtime=timedelta(hours=12),
        config=cfg,
        key_path=[STR.post],
        schema_file=Path("/s"),
    )
    if ready:
        run_shell_cmd.assert_called_once_with(
            ANY, callback=ANY, cwd=cls.return_value.rundir, taskname="20251001 18Z 012 post"
        )
    else:
        run_shell_cmd.assert_not_called()


@mark.parametrize(("hours", "ready"), [(-4, True), (0, False)])
def test_workflow__timegate(hours, ready):
    dt = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)
    node = workflow._timegate(dt)
    assert node.ready is ready
    cutoff = dt + timedelta(hours=3, minutes=35)
    assert node.taskname == "UTC > %s" % cutoff.replace(tzinfo=None)


def test_workflow__dt_taskname(cycle):
    assert workflow._dt_taskname(cycle, "foo") == (cycle, "20251001 18Z foo")
    assert workflow._dt_taskname("2025-10-01T18", "foo") == (cycle, "20251001 18Z foo")


def test_workflow__execute(capsys, lockkit):
    def run_cmd(*_args, **kwargs):
        kwargs["callback"](Mock(stdout=StringIO("first line\nsecond line\n")))
        output.touch()

    obj, assets, lockfile, output = lockkit
    with patch.object(workflow, "run_shell_cmd", side_effect=run_cmd) as cmd:
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    cmd.assert_called_once_with("/bin/true", callback=ANY, cwd=obj.rundir, taskname=TASKNAME)
    assert lockfile.is_file()
    assert output.is_file()
    assert capsys.readouterr().err == "first line\nsecond line\n"


def test_workflow__execute__ready_elsewhere(logcap, lockkit):
    obj, assets, _, output = lockkit
    output.touch()
    with patch.object(workflow, "run_shell_cmd") as cmd:
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    cmd.assert_not_called()
    assert f"{TASKNAME}: Made ready by another process" in logcap.text


def test_workflow__execute__locked(logcap, lockkit):
    obj, assets, lockfile, output = lockkit
    lockfile.parent.mkdir(parents=True)
    with patch.object(
        workflow, "run_shell_cmd", side_effect=lambda *_a, **_k: output.touch()
    ) as cmd:
        with lockfile.open("w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
            cmd.assert_not_called()
            assert not output.is_file()
            assert f"{TASKNAME}: Running in another process" in logcap.text
        # Lock released by holder, so the command now runs:
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    cmd.assert_called_once_with("/bin/true", callback=ANY, cwd=obj.rundir, taskname=TASKNAME)
    assert output.is_file()


def test_workflow__execute__lock_released(lockkit):
    obj, assets, lockfile, _ = lockkit
    with patch.object(workflow, "run_shell_cmd"):
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    with lockfile.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # would raise if still held


def test_workflow__fff():
    assert workflow._fff(Path("/path/to/aigfs.t00z.pres.f018.grib2")) == "018"


def test_workflow__passthrough_logger(capsys):
    logger = workflow._passthrough_logger()
    logger.info("some log message")
    assert capsys.readouterr().err.strip() == "some log message"
    assert workflow._passthrough_logger() is logger  # logging module reuses loggers


def test_workflow__schema():
    path = workflow._schema(AIGFSInference)
    assert path.name == "inference.jsonschema"
    assert path.is_file()


def test_workflow__utc():
    dt = datetime(1970, 1, 1)  # noqa: DTZ001
    assert dt.tzinfo is None
    dt = workflow._utc(dt)
    assert dt.tzinfo is UTC
