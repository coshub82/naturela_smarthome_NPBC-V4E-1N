import importlib.util
from pathlib import Path


def test_fuel_display_mapping() -> None:
    module_path = Path(__file__).resolve().parents[1] / "custom_components" / "naturela_smarthome" / "const.py"
    spec = importlib.util.spec_from_file_location("naturela_const_test", module_path)
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.fuel_to_display_value(0) == 1
    assert module.fuel_to_display_value(1) == 2
    assert module.fuel_to_display_value(2) == 3
    assert module.fuel_to_display_value(3) == 4
    assert module.fuel_to_display_value(4) == 1
