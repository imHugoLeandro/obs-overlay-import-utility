# Contributing

Bug reports and focused pull requests are welcome.

1. Create a branch from `main`.
2. Keep changes small and avoid adding customer overlay files to the repository.
3. Run `python -m unittest discover -s tests -v`.
4. Run `python -m compileall -q src tests`.
5. Explain the customer-visible behavior in the pull request.

Path matching must remain conservative: an ambiguous result should be reported, never guessed. Conversion must not overwrite or edit the original OBS collection.
