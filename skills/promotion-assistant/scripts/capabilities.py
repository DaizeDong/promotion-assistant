"""Describe shipped implementations and local resource availability without live probes."""
import os
from pathlib import Path

from . import providers, private_storage


def channels(cfg, env=None):
    env = cfg.runtime_env() if env is None else env
    rows = []
    for channel in cfg.channels():
        platform = channel.get('platform', channel.get('slug'))
        provider = providers.get(platform)
        mode = ('automated' if provider.LIVE_TRANSPORT else
                'manual-prep' if isinstance(provider, providers.ManualPrepProvider) else 'deferred')
        configured = mode == 'manual-prep'
        if platform == 'email':
            configured = (channel.get('email_helper_contract') == providers.email_contract.CONTRACT
                          and bool(env.get('PROMO_SEND_GMAIL'))
                          and Path(env['PROMO_SEND_GMAIL']).expanduser().is_file())
        elif platform == 'discord':
            configured = bool(env.get('PROMO_DISCORD_BOT_TOKEN') and
                              str(env.get('PROMO_DISCORD_ANNOUNCE_CHANNEL_ID', '')).isdigit())
        elif platform == 'mastodon':
            configured = bool(env.get('PROMO_MASTODON_INSTANCE') and env.get('PROMO_MASTODON_TOKEN'))
        elif platform == 'bluesky':
            configured = bool(env.get('PROMO_BLUESKY_HANDLE') and env.get('PROMO_BLUESKY_APP_PASSWORD'))
        rows.append({'slug': channel.get('slug'), 'platform': platform, 'mode': mode,
                     'implemented': mode != 'deferred', 'configured': bool(configured),
                     'live_proven': 'not_run'})
    return rows


def doctor(cfg, env=None, channel=None):
    rows = channels(cfg, env)
    rows = [row for row in rows if channel is None or row['slug'] == channel]
    names = private_storage.publication_destinations(cfg.root)
    checks = [{'name': message, 'ok': False} for message in cfg.settings_errors()]
    checks += [{'name': 'PRIVATE DATA publication destinations: '+', '.join(names), 'ok': True},
              {'name': 'selected channels exist', 'ok': bool(rows)}]
    checks.extend({'name': row['slug']+' resources', 'ok': row['implemented'] and row['configured']}
                  for row in rows)
    return {'status': 'ready' if all(check['ok'] for check in checks) else 'not_ready',
            'resolved_root': str(cfg.root), 'config_root': str(cfg.root),
            'checks': checks, 'channels': rows, 'live_proven': 'not_run',
            'scope': 'local implementation and resource checks; no live delivery probe'}
