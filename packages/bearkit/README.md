# 🐻 `bearkit`

The Python toolkit for the [Bear](https://bear.app) notes app: read notes
from Bear's database (read-only), write them through Bear's own API with
verification, search, and offline secret detection. macOS only.

```python
from bearkit import Bear

with Bear() as bear:
    for note in bear.list_notes(tag="work", limit=10):
        print(note.title)
```

Full API reference:
[docs/BEARKIT.md](https://github.com/michel-tricot/bearcli/blob/main/docs/BEARKIT.md).
`bearkit` powers [`bearcli`](https://pypi.org/project/bearcli/), the CLI and
terminal UI; install that for the full tool.
