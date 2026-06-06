# Repository todo List

Here is the list of remaining tasks and configuration items to complete for the `gh-workflows` repository:

## CI/CD & Automation

- [ ] **Create GitHub App for Automated Releases**
  - Required for the [tag.yaml](file:///Users/pawel/code/ghwm/.github/workflows/tag.yaml) workflow to run successfully.
  - **GitHub App Permissions Needed**:
    - **Repository contents**: Read & Write (to create/push release tags and create GitHub releases).
  - **Secrets to Configure**:
    - `GH_APP_ID`: Configure as a repository secret.
    - `GH_APP_PRIVATE_KEY`: Configure as a repository secret.
