"""Alembic environment configuration.

Loads the database URL from memoryhub_core.config at runtime, overriding
the placeholder in alembic.ini.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from memoryhub_core.config import DatabaseSettings

# Alembic Config object (provides access to alembic.ini values)
config = context.config

# Set up loggers from the config file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with the value from memoryhub settings
db_settings = DatabaseSettings()
config.set_main_option("sqlalchemy.url", db_settings.sync_url)

# Import models' MetaData for autogenerate support.
from memoryhub_core.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine.
    Calls to context.execute() emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
