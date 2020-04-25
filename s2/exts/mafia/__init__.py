from typing import Any, Dict, Optional, Union, cast

import discord
from discord.ext import commands

import lifesaver
from lifesaver.utils.formatting import codeblock

from .game import MafiaGame


class Mafia(lifesaver.Cog):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sessions: Dict[int, MafiaGame] = {}

    def get_game(
        self, ctx: Union[lifesaver.Context, discord.Guild]
    ) -> Optional[MafiaGame]:
        """Return the game according to the current context, or the game's guild."""

        if isinstance(ctx, discord.Guild):
            return discord.utils.get(self.sessions.values(), guild=ctx)

        if (game := self.sessions.get(ctx.channel.id)) is None:
            # since we're unable to fetch the game from the lobby channel, try
            # the guild that we're in
            assert ctx.guild is not None
            return self.get_game(ctx.guild)

        return game

    async def dispatch_to_game(
        self, event: str, guild: discord.Guild, *args, **kwargs
    ) -> None:
        """Dispatch an event for a game."""

        if (game := self.get_game(guild)) is None:
            return

        event_handler = getattr(game, event)

        try:
            await event_handler(*args, **kwargs)
        except Exception:
            self.log.exception(
                "something went wrong while passing %s to a mafia game", event
            )

    def _passthrough_event(event: str):  # type: ignore
        """Generate an event handler that passes events through to mafia games.

        We determine the target game through the ``guild`` property of the first
        parameter of the handler. It is assumed that events receive an entity with such
        property.
        """

        @lifesaver.Cog.listener(event)
        async def generated_event(self, entity: Any, *args, **kwargs):
            if (guild := entity.guild) is None:
                return

            await self.dispatch_to_game(event, guild, entity, *args, **kwargs)

        generated_event.__name__ = event

        return generated_event

    on_message = _passthrough_event("on_message")
    on_member_join = _passthrough_event("on_member_join")
    on_member_remove = _passthrough_event("on_member_remove")

    @lifesaver.group(hidden=True, invoke_without_command=True)
    @commands.guild_only()
    async def mafia(self, ctx: lifesaver.Context) -> None:
        """Starts a game of mafia"""
        if ctx.channel.id in self.sessions:
            await ctx.send("A game has already been started here...!")
            return

        creator = cast(discord.Member, ctx.author)
        lobby_channel = cast(discord.TextChannel, ctx.channel)
        channel_id = ctx.channel.id

        game = MafiaGame(ctx.bot, creator=creator, lobby_channel=lobby_channel, ctx=ctx)
        self.sessions[channel_id] = game

        try:
            await game.start()
        except Exception as err:
            await ctx.send(f"mafia machine broke: `{err!r}`")
            self.log.exception("error during mafia")
        finally:
            del self.sessions[channel_id]

    @mafia.group(name="debug", invoke_without_command=True)
    @commands.is_owner()
    @commands.guild_only()
    async def mafia_debug(self, ctx: lifesaver.Context) -> None:
        """Debugs mafia state"""
        if (game := self.get_game(ctx)) is None:
            await ctx.send("no game found?")
            return

        if (roster := game.roster) is None:
            await ctx.send("game hasn't started yet?")
            return

        players = "\n".join(
            f"{player}: {player.role.name}" for player in roster.players
        )

        debug_info = f"""{game.state=}

{game.lobby_channel=}
{game.creator=}

{game.role_chats=}
{game.role_state=}

{players}
"""

        await ctx.send(codeblock(debug_info))

    @mafia_debug.command(name="clean")
    @commands.is_owner()
    async def mafia_debug_clean(self, ctx: lifesaver.Context) -> None:
        """Deletes any guilds created for Mafia games"""
        for guild in ctx.bot.guilds:
            if "mafia " in guild.name and guild.owner == ctx.bot.user:
                await guild.delete()
        await ctx.ok()

    @mafia_debug.command(name="admin")
    @commands.is_owner()
    @commands.guild_only()
    async def mafia_debug_admin(self, ctx: lifesaver.Context) -> None:
        """Gives you admin"""
        if (game := self.get_game(ctx)) is None:
            await ctx.send("no game found?")
            return

        if (guild := game.guild) is None:
            await ctx.send("game area not found?")
            return

        permissions = discord.Permissions(administrator=True)

        role = await guild.create_role(
            name="debug admin", permissions=permissions, color=discord.Color.blue()
        )
        await cast(discord.Member, ctx.author).add_roles(role)
        await ctx.ok()

    @mafia_debug.command(name="slay")
    @commands.is_owner()
    @commands.guild_only()
    async def mafia_debug_slay(
        self, ctx: lifesaver.Context, target: discord.Member
    ) -> None:
        """Slays a player"""
        if (game := self.get_game(ctx)) is None:
            await ctx.send("no game found?")
            return

        if (roster := game.roster) is None:
            await ctx.send("game hasn't started yet?")
            return

        if (player := roster.get_player(target)) is None:
            await ctx.send("cannot find player")
            return

        await player.kill()
        await ctx.ok()


def setup(bot):
    bot.add_cog(Mafia(bot))
