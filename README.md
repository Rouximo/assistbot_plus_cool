# AssistBot+

**AssistBot+** is a lightweight **personalization tool for terminal environments** (such as Termux or Linux shells).
It allows users to customize their command-line experience by creating shortcuts, teaching responses, and running commands more efficiently from a single interactive interface.

The goal of AssistBot+ is simple: **make the terminal more personal, flexible, and fun to use.**

---

# What It Does

AssistBot+ acts as a small command-line assistant that lets you:

* Create **custom command shortcuts**
* Store **quick responses or notes**
* Run system commands easily
* Search the web from the terminal
* Organize frequently used actions
* Extend functionality through plugins

Instead of typing long commands repeatedly, you can create short custom triggers that run them instantly.

---

# Example

Create a command shortcut:

```bash
.map hello = echo Hello $1
```

Run it:

```bash
map hello Rouximo
```

Output:

```
Hello Rouximo
```

You can also store responses:

```bash
.teach quote = Stay curious | Keep learning
```

Then type:

```
quote
```

AssistBot+ will respond with one of the saved messages.

---

# Features

* Interactive terminal assistant
* Custom command mapping system
* Built-in knowledge storage (“brain”)
* Command history support
* Tab auto-completion
* Web search from terminal
* Plugin support
* SQLite-based storage
* Safe command filtering

---

# Designed For

AssistBot+ works well in environments like:

* Termux
* Linux terminals
* SSH shells
* developer CLI setups

It is especially useful for people who want to **personalize their command line workflow**.

---

# Running the Project

Run the assistant with:

```bash
python assistbot_plus_cool.py
```

Optional (for better UI):

```bash
pip install rich
```

---

# Storage

AssistBot+ stores its data locally using SQLite:

```
assistbot_plus.db
```

This file keeps:

* saved commands
* learned responses
* history entries

---

# Customization

Users can extend AssistBot+ by adding Python plugins inside the `plugins` directory.

---

# Project Goal

This project experiments with turning a normal terminal into a **more customizable and interactive environment**.

Instead of replacing the shell, AssistBot+ simply adds a layer of personalization on top of it.

---

# License

Open for learning, experimentation, and modification.
