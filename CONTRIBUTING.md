# Contributing

Thank you for your interest in improving `agent-containers`. Pull requests are
welcome. For a new image, a containment-policy change, or another substantial
change, please open an issue first so the intended design can be discussed.

## Development setup

You need Docker with Buildx support. Install [just](https://github.com/casey/just)
to run the repository's helper recipes, and install
[Zensical](https://zensical.org/) when changing documentation.

Clone the repository, then inspect the available recipes:

```sh
git clone https://github.com/anirbanbasu/agent-containers.git
cd agent-containers
just --list
```

Read [AGENTS.md](AGENTS.md) and
[the containment philosophy](docs/containment-philosophy.md) before changing
an image, entrypoint, or egress behaviour.

## Making a change

1. Create a focused branch from the current default branch.
2. Keep the containment posture intact: agents must run unprivileged, the
   root filesystem must remain usable as read-only, and egress must remain
   deny-by-default unless explicitly configured.
3. Document user-visible image changes in `docs/container-images/`, and
   update `README.md` and `SECURITY.md` where applicable.
4. When adding or removing an image directory, run:

   ```sh
   just update-issue-templates
   ```

5. Run the relevant checks before opening a pull request:

   ```sh
   just check-issue-templates
   zensical build --clean
   git diff --check
   ```

For a new or modified image, also build it with the shared context and
smoke-test the CLI with the documented read-only filesystem, capability, and
persistent-home-volume settings. Never include credentials or other secrets in
the image, a build argument, test output, or a pull request.

If you find a containment or isolation vulnerability, follow the private
reporting process in [SECURITY.md](SECURITY.md) rather than opening a public
issue.

## Licensing & Contributions

By contributing to this project, you agree to the following:

1. **License:** Your contributions are licensed under the
   [MIT License](LICENSE).
2. **Media and documentation:** You grant the maintainers the right to
   relicense documentation and media assets, but not source code, under a more
   permissive license in the future.
3. **Developer Certificate of Origin (DCO):** To keep a clear chain of
   ownership, signed-off commits are strongly encouraged.

## Developer Certificate of Origin (DCO)

By adding `Signed-off-by: Your Name <email@example.com>` to a commit message,
you certify that you have the right to submit the work under the terms of the
[Developer Certificate of Origin 1.1](https://developercertificate.org).

Use `git commit -s` to add the sign-off automatically. To protect your
privacy, you may use your GitHub-provided no-reply email address or another
email alias. A signed-off commit looks like this:

```text
Signed-off-by: Real Name <username@users.noreply.github.com>
```
