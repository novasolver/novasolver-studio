"""Published example URLs may differ from packaging-only release versions."""
import re

import pytest

from novastudio import examples


@pytest.fixture(autouse=True)
def isolated_examples(monkeypatch, tmp_path):
    monkeypatch.setattr(examples, 'data_dir', lambda: tmp_path)
    monkeypatch.delenv('NOVASTUDIO_EXAMPLES_URL', raising=False)


@pytest.mark.parametrize(('version', 'published'), [
    ('0.7.6', '0.7.6'),
    ('0.7.6.post1', '0.7.6'),
    ('0.7.6.post2', '0.7.6.post2'),
    ('0.7.6.dev1', '0.7.6.dev1'),
    ('0.8.0', '0.8.0'),
    ('0.8.0.post1', '0.8.0'),
])
def test_published_urls(monkeypatch, version, published):
    monkeypatch.setattr(examples, '__version__', version)
    github = f'https://github.com/novasolver/novasolver-studio/releases/download/v{published}/'
    mirror = f'https://novasolver.jp/dl/studio/examples/v{published}/'
    assert examples.base_urls() == [github, mirror]
    assert examples.base_url() == github
    assert examples.release_page() == f'https://github.com/novasolver/novasolver-studio/releases/tag/v{published}'


@pytest.mark.parametrize('override', ['https://example.test/custom', 'https://example.test/custom/'])
def test_override_for_packaging_release(monkeypatch, override):
    monkeypatch.setattr(examples, '__version__', '0.7.6.post1')
    monkeypatch.setenv('NOVASTUDIO_EXAMPLES_URL', override)
    assert examples.base_urls() == ['https://example.test/custom/']
    assert examples.base_url() == 'https://example.test/custom/'
    assert examples.release_page() == 'https://github.com/novasolver/novasolver-studio/releases/tag/v0.7.6'


def test_cache_isolated_by_full_version(monkeypatch, tmp_path):
    for version in ('0.7.6', '0.7.6.post1', '0.7.6.post2'):
        monkeypatch.setattr(examples, '__version__', version)
        cache = examples.cache_dir()
        assert cache == tmp_path / 'examples' / version
        assert cache.is_dir()
        assert not (cache / examples.INDEX).exists()
        (cache / examples.INDEX).write_text(version, encoding='utf-8')

    for version in ('0.7.6', '0.7.6.post1', '0.7.6.post2'):
        monkeypatch.setattr(examples, '__version__', version)
        assert (examples.cache_dir() / examples.INDEX).read_text(encoding='utf-8') == version


def test_this_version_points_at_a_real_tag():
    """A packaging-only release (PyPI .postN) has no GitHub tag, so it must name the release whose
    assets it reuses. Without the entry the examples 404 for everyone who installed that version:
    0.8.0.post1 shipped that way on 2026-11-13."""
    if re.search(r'\.post\d+$', examples.__version__):
        assert examples.__version__ in examples._PUBLISHED_VERSIONS, (
            f'{examples.__version__} is a packaging-only release with no tag of its own. '
            f'Add it to examples._PUBLISHED_VERSIONS, pointing at the released version whose '
            f'assets it reuses, or the solved examples 404 for every user.')
    assert not re.search(r'\.post\d+$', examples.release_page()), examples.release_page()
    for url in examples.base_urls():
        assert not re.search(r'\.post\d+/$', url), url
