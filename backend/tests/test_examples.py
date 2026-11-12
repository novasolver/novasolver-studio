"""Published example URLs may differ from packaging-only release versions."""
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
