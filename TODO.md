# Repository TODO List

Here is the list of remaining tasks and configuration items to complete for the `gh-workflows` repository:

## CI/CD & Automation

- [ ] **Create GitHub App for Automated Releases**
  * Required for the [tag.yaml](file:///Users/pawel/code/ghwm/.github/workflows/tag.yaml) workflow to run successfully.
  * **GitHub App Permissions Needed**:
    - **Repository contents**: Read & Write (to create/push release tags and create GitHub releases).
  * **Secrets to Configure**:
    - `GH_APP_ID`: Configure as a repository secret.
    - `GH_APP_PRIVATE_KEY`: Configure as a repository secret.

## Project Housekeeping

- [ ] **Review and Commit Local Workspace Changes**
  * Verify and commit the updated [README.md](file:///Users/pawel/code/ghwm/README.md).
  * Commit the updated [.textlintignore](file:///Users/pawel/code/ghwm/.github/linters/.textlintignore) (which fixes `.venv` glob matching for `textlint`).
  * Review and commit the new workflow definitions:
    - [linter.yaml](file:///Users/pawel/code/ghwm/.github/workflows/linter.yaml)
    - [tag.yaml](file:///Users/pawel/code/ghwm/.github/workflows/tag.yaml)
  * Decide whether to commit the project-local RTK files (`.rtk/filters.toml` and `CLAUDE.md`) or update `.gitignore`.
