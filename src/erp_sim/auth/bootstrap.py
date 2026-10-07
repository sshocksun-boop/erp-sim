"""Server shell bootstrap. The command is fixed; callers cannot inject shell code."""


def bootstrap_command(settings, keys):
    endpoint = f'{settings.callback_host}:{settings.listen_port - 6400}'
    command = (f'FGLSERVER="{endpoint}"; export FGLSERVER; FGLGUI=1; export FGLGUI; '
               f'_FGLFEID="{keys.feid}"; export _FGLFEID; '
               f'_FGLFEID2="{keys.feid2}"; export _FGLFEID2;'
               'printf "\\nSIM_ENV|%s|%s|%s|END\\n" "$FGLSERVER" "$_FGLFEID" "$_FGLFEID2";'
               'udm7;exit;')
    return command, f'SIM_ENV|{endpoint}|{keys.feid}|{keys.feid2}|END'.encode()
