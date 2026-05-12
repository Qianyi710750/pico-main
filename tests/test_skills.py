from pico import FakeModelClient, MiniAgent, SessionStore, SkillCatalog, WorkspaceContext, build_arg_parser
from pico.skills import parse_frontmatter


def build_workspace(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def write_skill(tmp_path, name, text):
    skill_dir = tmp_path / ".pico" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    return skill_dir / "SKILL.md"


def build_agent(tmp_path, outputs, **kwargs):
    workspace = build_workspace(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return MiniAgent(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def test_parse_frontmatter_supports_list_triggers():
    metadata, body = parse_frontmatter(
        "---\n"
        "name: test-doctor\n"
        "description: Fix tests\n"
        "triggers:\n"
        "  - pytest\n"
        "  - failing test\n"
        "---\n"
        "Run focused tests first.\n"
    )

    assert metadata["name"] == "test-doctor"
    assert metadata["description"] == "Fix tests"
    assert metadata["triggers"] == ["pytest", "failing test"]
    assert body == "Run focused tests first.\n"


def test_skill_catalog_discovers_skill_files(tmp_path):
    write_skill(
        tmp_path,
        "test-doctor",
        "---\nname: test-doctor\ndescription: Fix tests\ntriggers: [pytest]\n---\nRun focused tests first.\n",
    )

    catalog = SkillCatalog.load(tmp_path / ".pico" / "skills")

    assert catalog.names() == ["test-doctor"]
    assert catalog.select("please run pytest") == ("test-doctor",)
    assert "Run focused tests first." in catalog.render(("test-doctor",))


def test_agent_injects_auto_triggered_skill_into_prompt(tmp_path):
    write_skill(
        tmp_path,
        "test-doctor",
        "---\nname: test-doctor\ndescription: Fix tests\ntriggers:\n  - pytest\n---\n"
        "When active, inspect the failing test before editing.\n",
    )
    agent = build_agent(tmp_path, ["<final>Done.</final>"])

    assert agent.ask("Please fix the pytest failure") == "Done."

    prompt = agent.model_client.prompts[-1]
    assert "Active skills:" in prompt
    assert "### test-doctor" in prompt
    assert "inspect the failing test before editing" in prompt
    assert agent.last_prompt_metadata["active_skills"] == ["test-doctor"]


def test_agent_uses_explicit_skill_without_trigger_match(tmp_path):
    write_skill(
        tmp_path,
        "code-review",
        "---\nname: code-review\ndescription: Review changes\ntriggers: [review]\n---\n"
        "Lead with bugs and risks.\n",
    )
    agent = build_agent(tmp_path, ["<final>Done.</final>"], skill_names=["code-review"])

    assert agent.ask("Look at this repository") == "Done."

    assert "### code-review" in agent.model_client.prompts[-1]
    assert agent.last_prompt_metadata["active_skills"] == ["code-review"]


def test_repl_skill_selection_persists_in_session(tmp_path):
    write_skill(
        tmp_path,
        "repo-scout",
        "---\nname: repo-scout\ndescription: Map the repo\n---\nBuild a concise project map.\n",
    )
    agent = build_agent(tmp_path, ["<final>Ready.</final>"])

    assert agent.use_skills(["repo-scout"]) == "active skills: repo-scout"

    resumed = MiniAgent.from_session(
        model_client=FakeModelClient(["<final>Done.</final>"]),
        workspace=build_workspace(tmp_path),
        session_store=agent.session_store,
        session_id=agent.session["id"],
        approval_policy="auto",
    )

    assert resumed.ask("Continue") == "Done."
    assert "### repo-scout" in resumed.model_client.prompts[-1]


def test_cli_accepts_skill_options(tmp_path):
    args = build_arg_parser().parse_args(
        [
            "--cwd",
            str(tmp_path),
            "--skill",
            "test-doctor",
            "--skill",
            "code-review",
            "--skills-dir",
            str(tmp_path / "skills"),
        ]
    )

    assert args.skill == ["test-doctor", "code-review"]
    assert args.skills_dir == str(tmp_path / "skills")
