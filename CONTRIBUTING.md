# Contributing

Thanks for your interest! This project started in the advanced physics lab at the
University of Freiburg, and contributions from other labs are very welcome, especially:

- **Hardware reports.** Does it work with your spectrometer model? Output of
  `Verify.ps1` and the model's USB hardware ID help a lot.
- **Windows setup feedback.** The setup scripts have been statically reviewed but have
  seen few real machines yet.
- **Teaching material**: exercises or scripts built on the HTTP API.
- Bug fixes, documentation improvements and new spectrometer backends.

By taking part you agree to follow the [code of conduct](CODE_OF_CONDUCT.md).

## Reporting bugs

Open an issue with:

- what you did, what you expected and what happened;
- operating system and Python version (or "packaged .exe");
- spectrometer model, or "simulator";
- relevant output: the dashboard's error message, the server console, or for setup
  problems the log in `C:\ProgramData\OceanOptics\logs\`.

**Security problems:** please report them privately, see [SECURITY.md](SECURITY.md).

## Development setup

Everything except the hardware path runs on any OS, thanks to the built-in simulator.

```bash
cd spectro-dashboard
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                                           # about a second, no hardware needed
python run.py --sim                              # dashboard at http://127.0.0.1:8777/
```

Python 3.10 or newer. See [docs/development.md](docs/development.md) for the code
layout, the test strategy and how to add a backend.

## Pull requests

1. Keep changes focused; one topic per pull request.
2. Add or update tests. Behaviour that depends on timing or hardware can usually be
   tested with the fake backends in `spectro-dashboard/tests/test_acquisition.py`.
3. Update the documentation in `docs/` when you change behaviour, the API or the
   limits, and add a line to [CHANGELOG.md](CHANGELOG.md).
4. Make sure `pytest` passes. CI also checks the JavaScript and PowerShell syntax and
   builds and smoke-tests the Windows executable.
5. Match the style of the surrounding code: plain Python and JavaScript (no build
   step for the web page) and short comments that explain *why*.

Never commit Ocean Insight installers or other proprietary files; the
`windows/ocean-optics-setup/vendor/` folder is ignored by git for that reason.

## License

By contributing you agree that your contributions are licensed under the project's
[MIT license](LICENSE).
