"""DDBJ validator Web API（FastAPI）。

Web server と validator は別コンテナ（podman / podman compose）。
Web server が UUID を発行して run ディレクトリを作り、validator を呼び出す。
通常の CLI 実行では UUID は発行されない（この層は web 専用）。
"""
