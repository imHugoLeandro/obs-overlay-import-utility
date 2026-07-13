# Sync this project with GitHub

The project already has a local Git repository and a `main` branch. GitHub is the remote copy; pushing code is separate from building or distributing the executable.

## First-time setup

1. Sign in to GitHub and choose **New repository**.
2. Name it `obs-overlay-import-utility` and choose **Public** if you want it to be open source.
3. Do not add a README, `.gitignore`, or license on GitHub—the local project already contains them.
4. Create the repository.
5. Replace `<username>` below with your GitHub username, then run these commands from this project folder:

```powershell
git remote add origin https://github.com/<username>/obs-overlay-import-utility.git
git remote -v
git push -u origin main
```

If you use SSH authentication, use this remote instead:

```powershell
git remote add origin git@github.com:<username>/obs-overlay-import-utility.git
git push -u origin main
```

Also replace `YOUR-GITHUB-USERNAME` in `pyproject.toml`, then commit and push that small update.

## Normal sync workflow

Before starting work:

```powershell
git checkout main
git pull --ff-only origin main
git status
```

After making and testing a change:

```powershell
git status
git add README.md src tests
git commit -m "Describe the change clearly"
git push
```

Use `git add .` only after checking `git status` so generated files or personal data are not added by accident. The included `.gitignore` excludes build folders and virtual environments.

## Clone it on another computer

```powershell
git clone https://github.com/<username>/obs-overlay-import-utility.git
cd obs-overlay-import-utility
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Publish a release

Update the version and changelog, commit the change, then create and push a tag:

```powershell
git tag -a v2.0.0 -m "Release v2.0.0"
git push origin v2.0.0
```

The `Build Windows portable app` GitHub workflow will test and build an executable artifact for version tags. Open the workflow run on GitHub to retrieve the artifact. You can then create a GitHub Release for the tag and attach the executable or a ZIP containing the executable, overlay files, scene collection, and customer instructions.

## If GitHub asks for a password

GitHub does not accept account passwords for HTTPS Git operations. Sign in through Git Credential Manager when prompted, or use a personal access token or SSH key.
