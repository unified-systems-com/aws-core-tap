"""TAP AWS Core plugin AppConfig."""

from tap_plugins.base import TapPluginConfig


class AwsCoreConfig(TapPluginConfig):
    def ready(self) -> None:
        # Base ready() loads tap-plugin.toml and registers the plugin's
        # edges/types/editors/searches. It MUST run — without it the manifest
        # is never loaded and `import_plugin_grift` skips this plugin.
        super().ready()

        # Dual-existence registration: registers the runner and upserts the
        # on-grid Collector node (req-aws-collector-runtime-4). Imported here,
        # not at module top, so the pure engine subpackage stays import-light
        # and apps loading does not eagerly pull boto3 / the GRIFT importer.
        from tap_plugin.aws_core.collectors.boto3_collector.collector import (
            Boto3Collector,
        )
        from tap_cares.registry import register_collector
        from tap_plugin.aws_core.panels.baseline import AwsBaselinePanelType
        from tap_plugin.aws_core.panels.counts import AwsCountsPanelType
        from tap_plugin.aws_core.panels.scp_rulebook import AwsScpRulebookPanelType
        from tap_web.registry import panel_type_registry

        for panel_type in (AwsCountsPanelType, AwsBaselinePanelType, AwsScpRulebookPanelType):
            panel_type_registry.register(panel_type.slug, panel_type)

        register_collector(
            key="boto3",
            # Stable scope (plugin slug) so the derived entity id survives module
            # renames — see the fuller note in fedramp_20x_ksi/apps.py and
            # req-tap-cares-collector-model-10.
            scope="aws_core",
            cls=Boto3Collector,
            name="AWS Core Collector (boto3)",
            description=(
                "Collects a single AWS account into the grid via boto3, "
                "driven entirely by the aws_core resource manifest: typed "
                "nodes and declarative edges, submitted as one GRIFT batch "
                "per run. Each manifest entry declares whether its "
                "configuration blob is persisted."
            ),
        )
