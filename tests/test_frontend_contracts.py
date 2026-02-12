import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "static" / "index.html"
APP_JS = ROOT / "static" / "app.js"
STYLES_CSS = ROOT / "static" / "styles.css"


class FrontendContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = INDEX_HTML.read_text(encoding="utf-8")
        cls.app_js = APP_JS.read_text(encoding="utf-8")
        cls.styles = STYLES_CSS.read_text(encoding="utf-8")

    def test_index_has_auth_and_app_shell_regions(self) -> None:
        self.assertIn('id="authPanel"', self.index)
        self.assertIn('id="appShell"', self.index)
        self.assertIn('id="authForm"', self.index)
        self.assertIn('id="logoutBtn"', self.index)

    def test_index_has_filter_and_category_controls(self) -> None:
        expected_ids = [
            'id="subscriptionCategorySelect"',
            'id="newCategoryInput"',
            'id="addCategoryBtn"',
            'id="categoryList"',
            'id="searchInput"',
            'id="categoryFilterSelect"',
            'id="sortSelect"',
        ]
        for marker in expected_ids:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.index)

    def test_app_wires_critical_auth_endpoints(self) -> None:
        self.assertIn('"/api/auth/me"', self.app_js)
        self.assertIn('"/api/auth/signup"', self.app_js)
        self.assertIn('"/api/auth/login"', self.app_js)
        self.assertIn('"/api/auth/logout"', self.app_js)

    def test_app_wires_category_and_subscription_endpoints(self) -> None:
        self.assertIn('"/api/categories"', self.app_js)
        self.assertIn('"/api/subscriptions"', self.app_js)
        self.assertIn('"/api/reminders"', self.app_js)

    def test_app_has_filter_event_handlers(self) -> None:
        self.assertIn('searchInput.addEventListener("input", applyFiltersAndRender)', self.app_js)
        self.assertIn('categoryFilterSelect.addEventListener("change", applyFiltersAndRender)', self.app_js)
        self.assertIn('sortSelect.addEventListener("change", applyFiltersAndRender)', self.app_js)

    def test_styles_define_auth_and_filter_layout(self) -> None:
        selectors = [
            ".auth-panel",
            ".category-manager",
            ".filters-row",
            ".category-chip",
        ]
        for selector in selectors:
            with self.subTest(selector=selector):
                self.assertIn(selector, self.styles)


if __name__ == "__main__":
    unittest.main()
