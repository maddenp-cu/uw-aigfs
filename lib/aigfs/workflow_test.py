import fcntl
import os
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import ANY, Mock, patch

from iotaa import Asset
from pydantic import ValidationError
from pytest import fixture, mark, raises

from aigfs import workflow
from aigfs.drivers.inference import AIGFSInference
from aigfs.strings import STR

TASKNAME = "20251001 18Z 012 post"

# Fixtures:


@fixture
def cfg(tmp_path):
    path = tmp_path / "aigfs.yaml"
    with patch.object(workflow, "CONFIG", path), patch.object(workflow, "APPDIR", tmp_path):
        yield path


@fixture
def cycledirs(tmp_path):
    paths = [tmp_path / f"20261010{hh}" for hh in ("00", "06", "12")]
    for path in paths:
        path.mkdir()
    (tmp_path / "not-a-cycle").mkdir()
    (tmp_path / "2026101018").touch()  # cycle-like name, but a file
    return paths


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


# Helpers:


def driver(output: dict, rundir: Path) -> Mock:
    obj = Mock(output=output, rundir=rundir)
    return Mock(return_value=obj)


# Tests for validation classes:


def test_workflow_AppCycles(test_config):
    app = workflow.AppCycles.model_validate(test_config["app"])
    assert app.cycle_freq == timedelta(hours=12)
    assert app.first_cycle == test_config["app"]["first_cycle"]
    assert app.last_cycle == test_config["app"]["last_cycle"]


@mark.parametrize("delete", [True, False])
@mark.parametrize("field", ["cycle_freq", "first_cycle", "last_cycle"])
def test_workflow_AppCycles__required(delete, field, with_del, with_set, test_config):
    app = test_config["app"]
    app = with_del(app, field) if delete else with_set(app, None, field)
    with raises(ValidationError) as e:
        workflow.AppCycles.model_validate(app)
    assert e.value.errors()[0]["loc"] == (field,)


def test_workflow_AppRealtime(test_config):
    app_data = test_config["app"]
    del app_data["first_cycle"]
    del app_data["last_cycle"]
    app = workflow.AppRealtime.model_validate(app_data)
    assert app.cycle_freq == timedelta(hours=12)
    assert app.first_cycle is None
    assert app.last_cycle is None


@mark.parametrize("delete", [True, False])
def test_workflow_AppRealtime__required(delete, with_del, with_set, test_config):
    app = test_config["app"]
    app = with_del(app, "cycle_freq") if delete else with_set(app, None, "cycle_freq")
    with raises(ValidationError) as e:
        workflow.AppRealtime.model_validate(app)
    assert e.value.errors()[0]["loc"] == ("cycle_freq",)


def test_workflow_User():
    user = workflow.User(window_size=3)
    assert user.window_size == 3
    assert user.window_prune is False


@mark.parametrize(
    ("model", "app_model", "optional_cycles"),
    [
        (workflow.ConfigCycles, workflow.AppCycles, False),
        (workflow.ConfigRealtime, workflow.AppRealtime, True),
    ],
)
def test_workflow_Config(test_config, model, app_model, optional_cycles):
    test_config["user"] = {"extra_setting": ["ok"], "window_prune": False, "window_size": 3}
    if optional_cycles:
        del test_config["app"]["first_cycle"]
        del test_config["app"]["last_cycle"]
    c = model.model_validate(test_config)
    assert isinstance(c.app, app_model)
    assert c.user.model_dump() == test_config["user"]


@mark.parametrize("model", [workflow.ConfigCycles, workflow.ConfigRealtime])
@mark.parametrize(
    "user",
    [
        {},
        {"window_size": True},
        {"window_size": 0},
        {"window_size": -1},
        {"window_size": 3, "window_prune": 1},
    ],
)
def test_workflow_Config__user_bad(model, user, test_config):
    test_config["user"] = user
    with raises(ValidationError) as e:
        model.model_validate(test_config)
    assert e.value.errors()[0]["loc"][0] == "user"


@mark.parametrize("model", [workflow.ConfigCycles, workflow.ConfigRealtime])
def test_workflow_Config__user_missing(model, with_del, test_config):
    with raises(ValidationError) as e:
        model.model_validate(with_del(test_config, "user"))
    assert e.value.errors()[0]["loc"] == ("user",)


# Tests for public tasks:


def test_config__exists(cfg, touch):
    touch(cfg)
    with patch.object(workflow, "setup") as setup:
        node = workflow.config()
    assert node.ready
    assert node.taskname == "config"
    setup.compose_configs.assert_not_called()


@mark.usefixtures("cfg")
def test_config__missing(test_config, tmp_path):
    setup = Mock()
    setup.compose_configs.return_value = test_config
    with patch.object(workflow, "setup", setup):
        node = workflow.config()
    assert not node.ready
    setup.compose_configs.assert_called_once_with(
        workflow=None, platform="oci", user_config_files=[tmp_path / "user.yaml"]
    )
    setup.validate.assert_called_once_with(test_config)
    setup.set_up_rundir.assert_called_once_with(
        setup.validate.return_value, workflow=None, prefix="config"
    )


@mark.parametrize("ready", [True, False])
def test_workflow_cycle(atask, cycle, ready):
    with patch.object(workflow, STR.post, Mock(wraps=lambda _: atask(ready))) as post:
        node = workflow.cycle(cycle)
    assert node.ready is ready
    assert node.taskname == "20251001 18Z cycle"
    post.assert_called_once_with(cycle)


@mark.parametrize(
    "tz",
    [UTC, None, timezone(timedelta(hours=5))],  # UTC, naive (assumed UTC), and non-UTC
)
@mark.parametrize("ready", [True, False])
def test_workflow_cycles(atask, cycle, ready, tz):
    local = lambda dt: dt.replace(tzinfo=None) if tz is None else dt.astimezone(tz)
    c = workflow.ConfigCycles.model_construct(
        app=workflow.AppCycles.model_construct(
            first_cycle=local(cycle),
            last_cycle=local(cycle + timedelta(hours=12)),
            cycle_freq=timedelta(hours=6),
        )
    )
    with (
        patch.object(workflow, "_config", return_value=c),
        patch.object(workflow, "cycle", Mock(wraps=lambda _: atask(ready))) as cycle_,
    ):
        node = workflow.cycles()
    assert node.ready is ready
    assert node.taskname == "cycles"
    assert [x.args for x in cycle_.call_args_list] == [
        (cycle + timedelta(hours=12),),  # leading-edge first
        (cycle + timedelta(hours=6),),
        (cycle,),
    ]
    assert all(x.args[0].tzinfo is UTC for x in cycle_.call_args_list)


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


@mark.parametrize(
    ("now", "freq", "expected"),
    [
        # Mid-interval "now" rounds down to the latest cycle:
        ((14, 37, 12), 6, [(10, 12), (10, 6), (10, 0)]),
        # "Now" exactly on a cycle boundary is that cycle:
        ((12, 0, 0), 6, [(10, 12), (10, 6), (10, 0)]),
        # Daily cycles:
        ((14, 37, 12), 24, [(10, 0), (9, 0), (8, 0)]),
    ],
)
@mark.parametrize("prune", [True, False])
def test_workflow_realtime(atask, expected, freq, now, prune, tmp_path, utc):
    app = workflow.AppRealtime.model_construct(cycle_freq=timedelta(hours=freq), rundir=tmp_path)
    user = workflow.User(window_prune=prune, window_size=3)
    c = workflow.ConfigRealtime.model_construct(app=app, user=user)
    dt = Mock(wraps=datetime)
    dt.now.return_value = utc(2026, 10, 10, *now)
    with (
        patch.object(workflow, "_config", return_value=c),
        patch.object(workflow, "_prune", Mock(wraps=lambda *_: atask(ready=True))) as _prune,
        patch.object(workflow, "cycle", Mock(wraps=lambda _: atask(ready=True))) as cycle,
        patch.object(workflow, "datetime", dt),
    ):
        node = workflow.realtime()
    assert node.ready
    assert node.taskname == "3 realtime cycles"
    dt.now.assert_called_once_with(UTC)
    active = [call.args[0] for call in cycle.call_args_list]
    assert active == [utc(2026, 10, day, hour) for day, hour in expected]  # leading-edge first
    assert all(x.tzinfo is UTC for x in active)
    if prune:
        _prune.assert_called_once_with(tmp_path, 3)
    else:
        _prune.assert_not_called()


# Tests for private tasks:


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


@mark.parametrize("dry_run", [True, False])
def test_workflow__prune(cycledirs, dry_run, tmp_path):
    old, *recent = cycledirs
    node = workflow._prune(tmp_path, 2, iotaa={"dry_run": dry_run})
    assert node.taskname == f"Prune cycle directories in {tmp_path}"
    assert node.ready is not dry_run
    assert old.is_dir() is dry_run  # not deleted for dry run
    assert all(path.is_dir() for path in recent)
    assert (tmp_path / "not-a-cycle").is_dir()
    assert (tmp_path / "2026101018").is_file()


def test_workflow__prune__no_old_cycles(cycledirs, tmp_path):
    with patch.object(workflow, "rmtree") as rmtree:
        node = workflow._prune(tmp_path, 3)
    assert node.ready
    rmtree.assert_not_called()
    assert all(path.is_dir() for path in cycledirs)


def test_workflow__prune__no_rundir(tmp_path):
    with patch.object(workflow, "rmtree") as rmtree:
        assert workflow._prune(tmp_path / "missing", 2).ready
    rmtree.assert_not_called()


def test_workflow__prune__rmtree_error(cycledirs, logcap, tmp_path):
    old = cycledirs[0]
    failed = old / "somefile"
    err = PermissionError(13, "Permission denied", str(failed))

    def rmtree(_path, onexc):
        onexc(os.unlink, str(failed), err)

    with patch.object(workflow, "rmtree", side_effect=rmtree):
        node = workflow._prune(tmp_path, 2)
    assert not node.ready  # directory still present
    assert old.is_dir()
    assert f"Could not remove {failed}: {err}" in logcap.text


@mark.parametrize("tz", [UTC, timezone(timedelta(hours=5))])
@mark.parametrize(("hours", "ready"), [(-4, True), (0, False)])
def test_workflow__timegate(hours, ready, tz):
    dt = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)
    node = workflow._timegate(dt.astimezone(tz))
    assert node.ready is ready
    cutoff = dt + timedelta(hours=3, minutes=35)
    assert node.taskname == "UTC > %s" % cutoff.replace(tzinfo=None)  # always UTC


# Tests for private helpers:


def test_workflow__cmd(cycle, cfg, tmp_path):
    obj = Mock(__module__="aigfs.drivers.inference")
    obj.__class__.__name__ = "AIGFSInference"
    expected = (
        f"srun {tmp_path}/bin/run cmd uw execute --module aigfs.drivers.inference "
        f"--classname AIGFSInference --task run --config {cfg} --key-path forecast "
        "--cycle 20251001T18 --leadtime 12"
    )
    actual = workflow._cmd(obj, ["forecast"], cycle, leadtime=timedelta(hours=12), prefix="srun")
    assert actual == expected


@mark.parametrize(
    ("model", "expected_type"),
    [
        (workflow.ConfigCycles, workflow.ConfigCycles),
        (workflow.ConfigRealtime, workflow.ConfigRealtime),
    ],
)
def test_workflow__config(test_config, model, expected_type):
    test_config["user"] = {"window_size": 2}
    with patch.object(workflow, "realize_to_dict", return_value=test_config) as realize:
        workflow._config.cache_clear()
        try:
            c = workflow._config(model)
            assert isinstance(c, expected_type)
            realize.assert_called_once_with(workflow.CONFIG)
        finally:
            workflow._config.cache_clear()


@mark.parametrize(
    "cycle_",
    [
        datetime(2025, 10, 1, 18, tzinfo=UTC),
        datetime(2025, 10, 1, 18),  # noqa: DTZ001
        datetime(2025, 10, 1, 23, tzinfo=timezone(timedelta(hours=5))),
        "2025-10-01T18",
        "2025-10-01T23+05:00",
    ],
)
def test_workflow__dt_taskname(cycle, cycle_):
    dt, taskname = workflow._dt_taskname(cycle_, "foo")
    assert dt == cycle
    assert dt.tzinfo is UTC
    assert taskname == "20251001 18Z foo"


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


def test_workflow__execute__lock_released(lockkit):
    obj, assets, lockfile, _ = lockkit
    with patch.object(workflow, "run_shell_cmd"):
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    with lockfile.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # would raise if still held


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


def test_workflow__execute__ready_elsewhere(logcap, lockkit):
    obj, assets, _, output = lockkit
    output.touch()
    with patch.object(workflow, "run_shell_cmd") as cmd:
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    cmd.assert_not_called()
    assert f"{TASKNAME}: Made ready by another process" in logcap.text


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
    naive = datetime(1970, 1, 1, 12)  # noqa: DTZ001
    assert workflow._utc(naive) == datetime(1970, 1, 1, 12, tzinfo=UTC)  # assumed UTC
    plus5 = datetime(1970, 1, 1, 12, tzinfo=timezone(timedelta(hours=5)))
    assert workflow._utc(plus5) == datetime(1970, 1, 1, 7, tzinfo=UTC)  # converted
    for dt in (naive, plus5):
        assert workflow._utc(dt).tzinfo is UTC
