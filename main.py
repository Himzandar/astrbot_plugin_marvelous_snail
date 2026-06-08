from astrbot.api import llm_tool
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import command, command_group

from .core.account_feature import AccountFeatureMixin
from .core.plugin_base import MarvelousSnailPluginBase
from .core.strategy_feature import StrategyFeatureMixin


class MarvelousSnailPlugin(
    StrategyFeatureMixin,
    AccountFeatureMixin,
    MarvelousSnailPluginBase,
):
    """最强蜗牛插件，集成了账号管理和攻略查询功能，提供丰富的命令接口供用户使用。"""

    @command_group("最强蜗牛")
    def zqwn(self):
        """最强蜗牛攻略相关功能
        搜索，添加，删除，查看攻略作者
        """
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("作者搜索")
    async def search_public_account(
        self, event: AstrMessageEvent, keyword: str = "最强蜗牛", size: int = 5
    ):
        """搜索攻略作者实现函数，支持管理员搜索公共账号库中的攻略作者。
        Args:
            event: 消息事件对象。
            keyword: 搜索关键词，默认为 "最强蜗牛"。
            size: 返回结果数量，默认为 5。
        Returns:
            异步生成器，返回搜索结果。
        """
        async for result in self.search_public_account_impl(event, keyword, size):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("作者添加")
    async def add_saved_account(self, event: AstrMessageEvent, index: str):
        """添加已保存的账号实现函数，支持管理员将公共账号库中的账号添加到已保存账号列表。
        Args:
            event: 消息事件对象。
            index: 要添加的账号索引。
        Returns:
            异步生成器，返回添加结果。
        """
        async for result in self.add_saved_account_impl(event, index):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("作者删除")
    async def del_saved_account(self, event: AstrMessageEvent, name: str):
        """删除已保存的账号实现函数，支持管理员将已保存账号列表中的账号删除。
        Args:
            event: 消息事件对象。
            name: 要删除的账号名称。
        Returns:
            异步生成器，返回删除结果。
        """
        async for result in self.del_saved_account_impl(event, name):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("作者列表")
    async def list_saved_accounts(self, event: AstrMessageEvent):
        """列出已保存的账号实现函数，支持管理员查看已保存账号列表。
        Args:
            event: 消息事件对象。
        Returns:
            异步生成器，返回已保存账号列表。
        """
        async for result in self.list_saved_accounts_impl(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @zqwn.command("攻略推送列表")
    async def get_push_list(self, event: AstrMessageEvent):
        """获取攻略推送列表实现函数，支持管理员查看攻略推送列表。
        Args:
            event: 消息事件对象。
        Returns:
            异步生成器，返回攻略推送列表。
        """
        async for result in self.get_push_list_impl(event):
            yield result

    @zqwn.command("攻略推送")
    async def push_zqwn(self, event: AstrMessageEvent, enabled: str):
        """攻略推送实现函数，支持管理员开启或关闭攻略推送。
        Args:
            event: 消息事件对象。
            enabled: 是否启用攻略推送，取值为 "开启" 或 "关闭"。
        Returns:
            异步生成器，返回操作结果。
        """
        async for result in self.push_zqwn_impl(event, enabled):
            yield result

    @zqwn.command("搜索攻略")
    async def get_strategy(self, event: AstrMessageEvent, parse_str: str):
        """获取攻略实现函数，支持用户选择作者和文章进行查询。
        Args:
            event: 消息事件对象。
            parse_str: 查询字符串，用于搜索攻略。
        Returns:
            异步生成器，返回查询结果。
        """
        await self.get_strategy_impl(event, parse_str)

    @zqwn.command("特工逃犯")
    async def get_fugitives(self, event: AstrMessageEvent, name: str):
        """获取特工逃犯信息实现函数，支持用户查询特工逃犯的奖励信息。
        Args:
            event: 消息事件对象。
            name: 逃犯名称，用于搜索特工逃犯信息。
        Returns:
            异步生成器，返回特工逃犯信息。
        """
        async for result in self.get_fugitives_impl(event, name):
            yield result

    @command("绑定账号")
    async def get_headers(self, event: AstrMessageEvent, account: str):
        """获取账号信息实现函数，支持用户绑定最强蜗牛账号并获取相关信息。
        Args:
            event: 消息事件对象。
            account: 账号信息字符串，包含账号名称和相关信息。
        Returns:
            None
        """
        await self.get_headers_impl(event, account)

    @zqwn.command("批量绑定")
    async def batch_bind_accounts(self, event: AstrMessageEvent):
        """批量绑定账号实现函数，支持用户批量绑定最强蜗牛账号。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        await self.batch_bind_accounts_impl(event)

    @command("查询绑定")
    async def query_account(self, event: AstrMessageEvent):
        """查询绑定账号实现函数，支持用户查询已绑定的最强蜗牛账号。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        await self.query_account_impl(event)

    @command("注销绑定")
    async def delete_account(self, event: AstrMessageEvent):
        """删除绑定账号实现函数，支持用户删除已绑定的最强蜗牛账号。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        await self.delete_account_impl(event)

    @command("定时签到推送")
    async def schedule_sign(self, event: AstrMessageEvent, enabled: str):
        """定时签到推送实现函数，支持用户开启或关闭定时签到推送。
        Args:
            event: 消息事件对象。
            enabled: 是否启用定时签到推送，取值为 "开启" 或 "关闭"。
        Returns:
            异步生成器，返回操作结果。
        """
        async for result in self.schedule_sign_impl(event, enabled):
            yield result

    @command("定时签到进度")
    async def auto_sign_progress(self, event: AstrMessageEvent):
        """定时签到进度实现函数，支持用户查询定时签到的当前进度。
        Args:
            event: 消息事件对象。
        Returns:
            异步生成器，返回定时签到的当前进度。
        """
        yield event.plain_result(self._format_auto_sign_progress())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @command("强制执行自动签到")
    async def force_auto_sign(self, event: AstrMessageEvent):
        """强制执行自动签到实现函数，支持管理员强制执行一次自动签到。
        Args:
            event: 消息事件对象。
        Returns:
            None
        """
        await self.force_auto_sign_impl(event)

    @command("最强蜗牛help")
    async def show_help(self, event: AstrMessageEvent):
        """显示帮助信息实现函数，支持用户查看最强蜗牛插件的使用帮助。
        Args:
            event: 消息事件对象。
        Returns:
            异步生成器，返回帮助信息。
        """
        async for result in self.show_help_impl(event):
            yield result

    @command("账号统计")
    async def account_statistics(self, event: AstrMessageEvent):
        """账号统计实现函数，支持用户查看账号的统计信息。
        Args:
            event: 消息事件对象。
        Returns:
            异步生成器，返回账号统计信息。
        """
        async for result in self.account_statistics_impl(event):
            yield result

    #=============工具函数=============
    @llm_tool("send_code")
    async def send_code(self, event: AstrMessageEvent) -> None:
        """发送当前有效密令列表。仅在用户明确要求查看密令列表时才调用。
        调用前请严格判断：
        1. 用户是否明确要求查看当前有效密令、兑换码列表、全部密令？
        2. 如果用户只是闲聊、询问攻略、绑定账号、签到、特工逃犯等其他功能，请不要调用此工具。
        3. 如果用户只是提到“密令”但意图不明确，请先询问用户是否需要查看当前有效密令列表。
        4. 如果用户是在询问某一条密令的来源、使用方式、失效原因，或让你解释密令内容，请不要调用此工具，应直接回答。
        """
        await self.send_code_impl(event)
