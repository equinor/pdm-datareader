import os


def get_login_name():
    """
    A helper function which searches for the login name of the user.
    :return: The username of the user, if found. If not found, this function does not return anything.
    """
    env_names = ["LOGNAME", "USER", "LNAME", "USERNAME"]
    for name in env_names:
        if os.getenv(name) is not None:
            return os.getenv(name)
