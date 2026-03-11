import os
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from loguru import logger
from pydantic import BaseModel, Field

from ext_notification import send_notification


class Response(BaseModel):
    code: int = Field(..., alias="code", description="返回值")
    msg: str = Field(..., alias="msg", description="提示信息")
    success: Optional[bool] = Field(None, alias="success", description="token有时才有")
    data: Optional[Any] = Field(None, alias="data", description="请求成功才有")


class KurobbsClientException(Exception):
    """Custom exception for Kurobbs client errors."""
    pass


class KurobbsClient:
    FIND_ROLE_LIST_API_URL = "https://api.kurobbs.com/gamer/role/default"
    SIGN_URL = "https://api.kurobbs.com/encourage/signIn/v2"
    USER_SIGN_URL = "https://api.kurobbs.com/user/signIn"
    USER_MINE_URL = "https://api.kurobbs.com/user/mineV2"

    def __init__(self, token: str):
        self.token = token
        self.result: Dict[str, str] = {}
        self.exceptions: List[Exception] = []

    def get_headers(self) -> Dict[str, str]:
        """Get the headers required for API requests."""
        return {
            "osversion": "Android",
            "devcode": "2fba3859fe9bfe9099f2696b8648c2c6",
            "countrycode": "CN",
            "ip": "10.0.2.233",
            "model": "2211133C",
            "source": "android",
            "lang": "zh-Hans",
            "version": "1.0.9",
            "versioncode": "1090",
            "token": self.token,
            "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/3.10.0",
        }

    def make_request(self, url: str, data: Dict[str, Any]) -> Response:
        """Make a POST request to the specified URL with the given data."""
        headers = self.get_headers()
        response = requests.post(url, headers=headers, data=data)
        res = Response.model_validate_json(response.content)
        logger.debug(res.model_dump_json(indent=2, exclude={"data"}))
        return res

    def get_mine_info(self, type: int = 1):
        """Get mine info"""
        data = {"type": type}
        res = self.make_request(self.USER_MINE_URL, data)
        return res.data

    def get_user_game_list(self, user_id: int) -> List[Dict[str, Any]]:
        """Get the list of games for the user."""
        data = {"queryUserId": user_id}
        res = self.make_request(self.FIND_ROLE_LIST_API_URL, data)
        return res.data

    def checkin(self) -> Response:
        """Perform the check-in operation."""
        mine_info = self.get_mine_info()
        user_game_list = self.get_user_game_list(user_id=mine_info.get("mine", {}).get("userId", 0))
        # 获取北京时间（UTC+8）
        beijing_tz = ZoneInfo('Asia/Shanghai')
        beijing_time = datetime.now(beijing_tz)

        # role_info = user_game_list.get("defaultRoleList", [])[0]
        role_list = user_game_list.get("defaultRoleList", [])
        if not role_list:
            raise KurobbsClientException("未找到游戏角色")

        role_info = role_list[0]
        
        data = {
            "gameId": role_info.get("gameId", 2),
            "serverId": role_info.get("serverId", None),
            "roleId": role_info.get("roleId", 0),
            "userId": role_info.get("userId", 0),
            "reqMonth": f"{beijing_time.month:02d}",
        }
        return self.make_request(self.SIGN_URL, data)

    def sign_in(self) -> Response:
        """Perform the sign-in operation."""
        return self.make_request(self.USER_SIGN_URL, {"gameId": 2})

    def _process_sign_action(
            self,
            action_name: str,
            action_method: Callable[[], Response],
            success_message: str,
            failure_message: str,
    ):
        """
        Handle the common logic for sign-in actions.

        :param action_name: The name of the action (used to store the result).
        :param action_method: The method to call for the sign-in action.
        :param success_message: The message to log on success.
        :param failure_message: The message to log on failure.
        """
        resp = action_method()
        logger.debug(resp)
        if resp.success:
            self.result[action_name] = success_message
        else:
            self.exceptions.append(KurobbsClientException(f'{failure_message}, {resp.msg}'))

    def start(self):
        """Start the sign-in process."""
        self._process_sign_action(
            action_name="checkin",
            action_method=self.checkin,
            success_message="签到奖励签到成功",
            failure_message="签到奖励签到失败",
        )

        self._process_sign_action(
            action_name="sign_in",
            action_method=self.sign_in,
            success_message="社区签到成功",
            failure_message="社区签到失败",
        )

        self._log()

    @property
    def msg(self):
        return ", ".join(self.result.values()) + "!"

    def _log(self):
        """Log the results and raise exceptions if any."""
        if msg := self.msg:
            logger.info(msg)
        if self.exceptions:
            raise KurobbsClientException("; ".join(map(str, self.exceptions)))


def configure_logger(debug: bool = False):
    """Configure the logger based on the debug mode."""
    logger.remove()  # Remove default logger configuration
    log_level = "DEBUG" if debug else "INFO"
    logger.add(sys.stdout, level=log_level)


def main():
    """Main function to handle command-line arguments and start the sign-in process."""
    # token = os.getenv("TOKEN")
    tokens = os.getenv("TOKEN").split("#")
    debug = os.getenv("DEBUG", False)

    all_msg = []
    
    for index, token in enumerate(tokens, start=1):
        try:
            kurobbs = KurobbsClient(token)
            kurobbs.start()
            if kurobbs.msg:
                all_msg.append(f"账号{index}：{kurobbs.msg}")
        except KurobbsClientException as e:
            logger.error(f"账号{index}签到失败: {str(e)}", exc_info=False)
            all_msg.append(f"账号{index}签到失败: {str(e)}")
            sys.exit(1)
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")
            sys.exit(1)

    # 汇总通知
    if all_msg:
        send_notification("\n".join(all_msg))

if __name__ == "__main__":
    main()
