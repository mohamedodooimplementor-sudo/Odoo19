def post_init_hook(env):
    env['res.company'].search([])._rc_ensure_locations()
