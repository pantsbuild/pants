import pathlib
import uuid

tmpdir = pathlib.Path(input("where is the tempdir?"))
for i in range(400):
    (tmpdir / "src" / f"{uuid.uuid4().hex}.txt").touch()
