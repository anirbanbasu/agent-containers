---
icon: lucide/shield-check
---

# Why hardened containers for coding agents?

Here's a scenario. You've hired someone brilliant to help around the house. Genuinely brilliant — they can fix the boiler, reorganise the shed, even nip out to the shops when you're low on milk. There's just one small catch: to do any of that, you've had to give them a key to every room in the house, including the one with your passport, your bank statements, and your grandmother's jewellery. Oh, and they've also got your car keys, so they can pop out whenever they like, to wherever they like, without _necessarily_ telling you first.

That, it turns out, is roughly the deal we've been striking with **coding agents**.

A (command-line) coding agent — the kind that can, backed by generative artificial intelligence (AI) models, read your files, run a build, install packages, and shell out to fix whatever's broken, all without you typing a single command yourself — is brilliant precisely *because* of that access. But here's the catch: that list of superpowers is also the entire problem. Every capability is a door, and the agent doesn't always know which door it's just walked through. A stray instruction hidden in a scraped web page, a typosquatted package that slipped in during a routine install, or simply the model having what we might charitably call an off day — any one of these can turn a helpful assistant into something with the run of your home directory, your stored credentials, and the open Internet. Not because it's gone rogue. Just because, on a bare host, that access was sitting there all along, waiting to be used.

## The bargain nobody actually agreed to

Here's the bit that should give you pause. Run an agent directly on your machine, and — whether you meant to or not — you've quietly signed up to the following:

- it can read anything your user account can read: SSH keys, cloud credentials, browser profiles, every other project sitting on that machine;
- it can write and delete just as freely, at whatever pace it happens to be working;
- it can talk to any host on the Internet, which means a bad instruction doesn't stay politely local — data can slip out, malicious payloads can be pulled in, a compromised process can quietly phone home;
- and the entire boundary between "a contained mistake" and "an uncontained one" is a single permission prompt — one you approved somewhere around the fifth "yes" of a long, tired session!

None of this is a flaw in any particular agent. It's just what happens when you hand a generative AI model access to a real shell, a real filesystem, and real network, and ask it to get on with things. And as these agents get more autonomous and run for longer stretches unsupervised, there are fewer and fewer moments where a human even *could* step in and catch the bad step before it happens.

## So here's the satisfying bit

The instinct might be to solve this with better prompting — to simply ask the agent, nicely, to be careful. That's not the answer. You can't negotiate your way out of a design flaw.

The actual fix is almost embarrassingly mechanical: stop relying on the model's judgement, and make the size of the mess a property of the *environment* instead.

Here's a useful bit of throat-clearing: think of the image as the blueprint, not the house — a frozen, read-only template sitting quietly on disk, waiting to be switched on into a running container.

Every image runs as a non-root user, on a read-only root filesystem, with Linux capabilities stripped down to only what the coding agent genuinely needs. Outbound network access is **denied by default**, and opened only against an explicit allowlist or through a dedicated _gateway_. Nothing here depends on the agent choosing to behave. It simply limits what bad behaviour could ever reach in the first place — because a sandbox that relies on the thing inside it respecting its own walls was never really a sandbox at all.

Picture it laid out: the host machine on one side, the container sitting inside it, and the network stretching out beyond both.

The coding agent lives inside that container as an unprivileged process. Only the one project directory chosen for the task at hand is allowed to cross the boundary, via an explicit bind mount — the rest of the host filesystem, credentials and other projects included, simply has no path in. It doesn't exist, as far as the agent is concerned. Outbound traffic gets the same treatment: every connection is checked before it's allowed anywhere near the Internet, and anything not explicitly permitted is quietly dropped.

## And it's not just about one agent

None of this risk is unique to any single tool. Claude Code is where this particular project began, but the underlying pattern — restricted by default, hardened at the container's edge, configurable rather than permissive — is built to generalise. All coding agents inherit the same walls.
