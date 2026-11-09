from alembic import command
from conftest import alembic_config
from sqlalchemy import inspect, text

OLD_DEFAULT = """\
<p><strong>{{tracker_name}}</strong>: week ending {{week_ending}}</p>
<p><strong>Status:</strong> {{status}} – {{verdict}}</p>
<p>Forecast completion {{forecast_date}} against a target of {{target_date}}.
{{percent_complete}} complete ({{completed}} of {{total_scope}}; {{remaining}} remaining).</p>
<p>{{headline}}</p>
<p><strong>Needed from you:</strong> {{decisions}}</p>
<p><a href="{{report_link}}">Open the live report</a> (sign-in required).</p>
"""


def test_upgrade_sets_the_single_direct_owner_in_charge_and_drops_old_default_messages(
    db, tracker_factory, user_factory
):
    one, two, none = tracker_factory(name="One"), tracker_factory(name="Two"), tracker_factory(name="None")
    ann, bob, cat = user_factory(full_name="Ann"), user_factory(full_name="Bob"), user_factory(full_name="Cat")
    db.commit()
    try:
        command.downgrade(alembic_config(), "0008")
        assert "lead_user_id" not in {c["name"] for c in inspect(db.connection()).get_columns("trackers")}
        roles = [(ann.id, one.id, "owner"), (cat.id, one.id, "editor"), (ann.id, two.id, "owner"),
                 (bob.id, two.id, "owner"), (cat.id, none.id, "editor")]  # fmt: skip
        for user_id, tracker_id, role in roles:
            db.execute(
                text("INSERT INTO tracker_roles (user_id, tracker_id, role) VALUES (:u, :t, :r)"),
                {"u": user_id, "t": tracker_id, "r": role},
            )
        db.execute(
            text(
                "INSERT INTO email_templates (tracker_id, subject, body_html) VALUES (:a, 's', :old), (:b, 's', :own)"
            ),
            {"a": one.id, "old": OLD_DEFAULT.replace("\n", "\r\n") + "  ", "b": two.id, "own": "<p>Our own</p>"},
        )
        db.commit()
        command.upgrade(alembic_config(), "head")
        leads = dict(db.execute(text("SELECT name, lead_user_id FROM trackers")).all())
        assert leads == {"One": ann.id, "Two": None, "None": None}
        kept = db.execute(text("SELECT tracker_id FROM email_templates")).scalars().all()
        assert kept == [two.id]
        assert "report_reminders" in inspect(db.connection()).get_table_names()
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
