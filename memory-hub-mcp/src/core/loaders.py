import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from typing import Iterable

from fastmcp import FastMCP
from .logging import get_logger

log = get_logger("loaders")


def _iter_modules(dir_path: Path, package_prefix: str) -> Iterable[str]:
    if not dir_path.exists():
        return []
    return (
        f"{package_prefix}.{name}"
        for _, name, _ in pkgutil.iter_modules([str(dir_path)])
    )


def _load_module_from_path(module_name: str, file_path: Path) -> None:
    """Dynamically load a module from a file path with a synthetic module name."""
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    else:  # pragma: no cover - defensive fallback
        importlib.import_module(module_name)


def load_tools(mcp: FastMCP, tools_dir: Path) -> int:
    """Load tool modules using package import names consistently with hot‑reload.

    We import modules as "src.tools.<name>" so that hot‑reload can safely reload the
    same module names without creating duplicate registrations.
    """
    added = 0
    if not tools_dir.exists():
        return 0
    for py_file in tools_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        module_name_pkg = f"src.tools.{py_file.stem}"
        module_name_synth = f"src_tools__{py_file.stem}"
        try:
            # Prefer package import if available
            importlib.import_module(module_name_pkg)
            log.info(f"Loaded tool module: {module_name_pkg}")
            added += 1
        except Exception:
            try:
                _load_module_from_path(module_name_synth, py_file)
                log.info(f"Loaded tool module (synthetic): {module_name_synth}")
                added += 1
            except Exception:
                log.exception(f"Failed to load tool: {py_file}")
    return added


def load_resources(mcp: FastMCP, resources_dir: Path) -> int:
    """Load resource modules using package import names consistently.

    Supports subdirectories: resources/country-profiles/japan.py becomes
    src.resources.country_profiles.japan.
    """
    added = 0
    if not resources_dir.exists():
        return 0

    # Use rglob to find all .py files recursively
    for py_file in resources_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue

        # Calculate relative path from resources_dir and build module name
        rel_path = py_file.relative_to(resources_dir)
        parts = list(rel_path.parts[:-1]) + [rel_path.stem]  # Remove .py and split path
        module_suffix = ".".join(parts)

        module_name_pkg = f"src.resources.{module_suffix}"
        module_name_synth = f"src_resources__{module_suffix.replace('.', '__')}"

        try:
            importlib.import_module(module_name_pkg)
            log.info(f"Loaded resource module: {module_name_pkg}")
            added += 1
        except Exception:
            try:
                _load_module_from_path(module_name_synth, py_file)
                log.info(f"Loaded resource module (synthetic): {module_name_synth}")
                added += 1
            except Exception:
                log.exception(f"Failed to load resource: {py_file}")
    return added


def load_prompts(mcp: FastMCP, prompts_dir: Path) -> int:
    """Load prompt modules using package import names consistently.

    Prompts are now defined using Python decorators (@mcp.prompt()) rather than
    YAML files. This function loads prompt modules from src/prompts/ directory.
    """
    added = 0
    if not prompts_dir.exists():
        return 0
    for py_file in prompts_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        module_name_pkg = f"src.prompts.{py_file.stem}"
        module_name_synth = f"src_prompts__{py_file.stem}"
        try:
            importlib.import_module(module_name_pkg)
            log.info(f"Loaded prompt module: {module_name_pkg}")
            added += 1
        except Exception:
            try:
                _load_module_from_path(module_name_synth, py_file)
                log.info(f"Loaded prompt module (synthetic): {module_name_synth}")
                added += 1
            except Exception:
                log.exception(f"Failed to load prompt: {py_file}")
    return added


def load_middleware(mcp: FastMCP, middleware_dir: Path) -> int:
    """Load middleware classes and register them with FastMCP.

    Middleware classes inherit from fastmcp.server.middleware.Middleware
    and override specific hook methods (on_call_tool, on_request, etc.).

    This function:
    1. Imports middleware modules from the middleware directory
    2. Finds Middleware subclasses in each module
    3. Instantiates and registers them with mcp.add_middleware()
    """
    added = 0
    if not middleware_dir.exists():
        return 0

    # Import the Middleware base class for isinstance checking
    try:
        from fastmcp.server.middleware import Middleware as FastMCPMiddleware
    except ImportError:
        log.warning("fastmcp.server.middleware not available; middleware disabled")
        return 0

    for py_file in middleware_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue

        module_name_pkg = f"src.middleware.{py_file.stem}"
        module_name_synth = f"src_middleware__{py_file.stem}"

        try:
            # Import the module
            try:
                module = importlib.import_module(module_name_pkg)
            except ImportError:
                module = importlib.util.module_from_spec(
                    importlib.util.spec_from_file_location(module_name_synth, py_file)
                )
                sys.modules[module_name_synth] = module
                module.__spec__.loader.exec_module(module)

            # Find and instantiate Middleware classes
            for name in dir(module):
                obj = getattr(module, name)
                # Check if it's a class that inherits from Middleware (but not Middleware itself)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, FastMCPMiddleware)
                    and obj is not FastMCPMiddleware
                ):
                    try:
                        middleware_instance = obj()
                        mcp.add_middleware(middleware_instance)
                        log.info(
                            f"Registered middleware: {name} from {module_name_pkg}"
                        )
                        added += 1
                    except Exception:
                        log.exception(f"Failed to instantiate middleware {name}")

        except Exception:
            log.exception(f"Failed to load middleware from: {py_file}")

    return added


# ---------------------------
# Hot‑reload (dev only)
# ---------------------------
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except Exception:  # pragma: no cover
    Observer = None
    FileSystemEventHandler = object  # type: ignore


class _ReloadHandler(FileSystemEventHandler):  # type: ignore[misc]
    def __init__(self, mcp: FastMCP, base: Path) -> None:
        self.mcp = mcp
        self.base = base

    def on_any_event(self, event):  # noqa: N802
        try:
            importlib.invalidate_caches()
            tools_dir = self.base / "tools"
            resources_dir = self.base / "resources"
            prompts_dir = self.base / "prompts"
            middleware_dir = self.base / "middleware"

            for module_name in list(_iter_modules(tools_dir, "src.tools")):
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)

            for module_name in list(_iter_modules(resources_dir, "src.resources")):
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)

            for module_name in list(_iter_modules(prompts_dir, "src.prompts")):
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)

            for module_name in list(_iter_modules(middleware_dir, "src.middleware")):
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)

            log.info("Hot‑reload applied")
        except Exception:
            log.exception("Hot‑reload failed")


def start_hot_reload(mcp: FastMCP, base_dir: Path):
    if Observer is None:
        log.warning("watchdog not installed; hot‑reload disabled")
        return None

    handler = _ReloadHandler(mcp, base_dir)
    obs = Observer()

    tools_dir = base_dir / "tools"
    resources_dir = base_dir / "resources"
    prompts_dir = base_dir / "prompts"
    middleware_dir = base_dir / "middleware"

    # Watch resources recursively to support subdirectories
    for d in (tools_dir, prompts_dir, middleware_dir):
        if d.exists():
            obs.schedule(handler, str(d), recursive=False)

    # Watch resources directory recursively
    if resources_dir.exists():
        obs.schedule(handler, str(resources_dir), recursive=True)

    obs.daemon = True
    obs.start()
    log.info(
        f"Hot‑reload watching: {tools_dir}, {resources_dir}, {prompts_dir}, {middleware_dir}"
    )
    return obs


def load_all(mcp: FastMCP, src_base: Path) -> dict:
    counts = {
        "tools": load_tools(mcp, src_base / "tools"),
        "resources": load_resources(mcp, src_base / "resources"),
        "prompts": load_prompts(mcp, src_base / "prompts"),
        "middleware": load_middleware(mcp, src_base / "middleware"),
    }
    log.info(f"Loaded: {counts}")
    return counts
