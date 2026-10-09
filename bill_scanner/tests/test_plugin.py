"""Phase 1: the plugin is discovered and exposes its settings."""

from plugin import registry
from plugin.models import PluginSetting

from bill_scanner.core import BillScannerPlugin
from bill_scanner.tests.base import SLUG, PluginTestCase


class PluginRegistrationTest(PluginTestCase):
    """The plugin loads into InvenTree's registry."""

    def test_plugin_is_registered(self):
        """The registry knows the plugin by its slug."""
        plugin = registry.get_plugin(SLUG)
        self.assertIsNotNone(plugin)
        # The registry may reload the module, so compare by name, not identity.
        self.assertEqual(plugin.NAME, BillScannerPlugin.NAME)

    def test_plugin_in_plugin_list_api(self):
        """The plugin appears in the admin plugin list."""
        self.user.is_superuser = True
        self.user.save()
        response = self.get('/api/plugins/', expected_code=200)
        keys = [item['key'] for item in response.data]
        self.assertIn(SLUG, keys)

    def test_api_key_setting_defined(self):
        """GEMINI_API_KEY is a required, protected setting."""
        definition = BillScannerPlugin.SETTINGS['GEMINI_API_KEY']
        self.assertTrue(definition['protected'])
        self.assertTrue(definition['required'])

    def test_api_key_round_trip(self):
        """The key is stored against the plugin, never hard-coded."""
        self.assertEqual(self.plugin.get_setting('GEMINI_API_KEY'), '')
        self.plugin.set_setting('GEMINI_API_KEY', 'secret-123')
        self.assertEqual(self.plugin.get_setting('GEMINI_API_KEY'), 'secret-123')
        stored = PluginSetting.objects.get(plugin__key=SLUG, key='GEMINI_API_KEY')
        self.assertEqual(stored.value, 'secret-123')

    def test_api_key_hidden_from_api(self):
        """The settings API masks the protected key."""
        self.plugin.set_setting('GEMINI_API_KEY', 'secret-123')
        self.user.is_superuser = True
        self.user.save()
        url = f'/api/plugins/{SLUG}/settings/GEMINI_API_KEY/'
        response = self.get(url, expected_code=200)
        self.assertEqual(response.data['value'], '***')
