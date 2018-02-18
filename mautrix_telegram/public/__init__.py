# -*- coding: future_fstrings -*-
# mautrix-telegram - A Matrix-Telegram puppeting bridge
# Copyright (C) 2018 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
from aiohttp import web
from mako.template import Template
import asyncio
import pkg_resources
import logging

from telethon.errors import *

from ..user import User
from ..commands.auth import enter_password


class PublicBridgeWebsite:
    log = logging.getLogger("mau.public")

    def __init__(self, loop):
        self.loop = loop

        self.login = Template(
            pkg_resources.resource_string("mautrix_telegram", "public/login.html.mako"))

        self.app = web.Application(loop=loop)
        self.app.router.add_route("GET", "/login", self.get_login)
        self.app.router.add_route("POST", "/login", self.post_login)
        self.app.router.add_static("/",
                                   pkg_resources.resource_filename("mautrix_telegram", "public/"))

    async def get_login(self, request):
        return self.render_login(
            request.rel_url.query["mxid"] if "mxid" in request.rel_url.query else "")

    def render_login(self, mxid, state="request", phone="", code="", password="",
                     error="", message="", username="", status=200):
        return web.Response(status=status,
                            content_type="text/html",
                            text=self.login.render(mxid=mxid, state=state, phone=phone, code=code,
                                                   message=message, username=username, error=error,
                                                   password=password))

    async def post_login(self, request):
        self.log.debug(request)
        data = await request.post()
        if "mxid" not in data:
            return self.render_login(error="Please enter your Matrix ID.", status=400)

        user = User.get_by_mxid(data["mxid"])
        if not user.whitelisted:
            return self.render_login(mxid=user.mxid, error="You are not whitelisted.", status=403)

        if "phone" in data:
            try:
                await user.client.sign_in(data["phone"] or "+123")
                return self.render_login(mxid=user.mxid, state="code", status=200,
                                         message="Code requested successfully.")
            except PhoneNumberInvalidError:
                return self.render_login(mxid=user.mxid, state="request", status=400,
                                         error="Invalid phone number.")
            except PhoneNumberUnoccupiedError:
                return self.render_login(mxid=user.mxid, state="request", status=404,
                                         error="That phone number has not been registered.")
            except PhoneNumberFloodError:
                return self.render_login(
                    mxid=user.mxid, state="request", status=429,
                    error="Your phone number has been temporarily banned for flooding. "
                          "The ban is usually applied for around a day.")
            except PhoneNumberBannedError:
                return self.render_login(mxid=user.mxid, state="request", status=401,
                                         error="Your phone number is banned from Telegram.")
            except PhoneNumberAppSignupForbiddenError:
                return self.render_login(mxid=user.mxid, state="request", status=401,
                                         error="You have disabled 3rd party apps on your account.")
            except Exception:
                self.log.exception("Error requesting phone code")
                return self.render_login(mxid=user.mxid, state="request", status=500,
                                         error="Internal server error while requesting code.")
        elif "code" in data:
            try:
                user_info = await user.client.sign_in(code=data["code"])
                asyncio.ensure_future(user.post_login(user_info), loop=self.loop)
                if user.command_status.action == "Login":
                    user.command_status = None
                return self.render_login(mxid=user.mxid, state="logged-in", status=200,
                                         username=user_info.username)
            except PhoneCodeInvalidError:
                return self.render_login(mxid=user.mxid, state="code", status=403,
                                         error="Incorrect phone code.")
            except PhoneCodeExpiredError:
                return self.render_login(mxid=user.mxid, state="code", status=403,
                                         error="Phone code expired.")
            except SessionPasswordNeededError:
                if "password" not in data:
                    if user.command_status.action == "Login":
                        user.command_status = {
                            "next": enter_password,
                            "action": "Login (password entry)",
                        }
                    return self.render_login(
                        mxid=user.mxid, state="password", status=200,
                        error="Code accepted, but you have 2-factor authentication is enabled.")
            except Exception:
                self.log.exception("Error sending phone code")
                return self.render_login(mxid=user.mxid, state="code", status=500,
                                         error="Internal server error while sending code.")
        elif "password" not in data:
            return self.render_login(error="No data given.", status=400)

        if "password" in data:
            try:
                user_info = await user.client.sign_in(password=data["password"])
                asyncio.ensure_future(user.post_login(user_info), loop=self.loop)
                if user.command_status.action == "Login (password entry)":
                    user.command_status = None
                return self.render_login(mxid=user.mxid, state="logged-in", status=200,
                                         username=user_info.username)
            except (PasswordHashInvalidError, PasswordEmptyError):
                return self.render_login(mxid=user.mxid, state="password", status=400,
                                         error="Incorrect password.")
            except Exception:
                self.log.exception("Error sending password")
                return self.render_login(mxid=user.mxid, state="password", status=500,
                                         error="Internal server error while sending password.")
