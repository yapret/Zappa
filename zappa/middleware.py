import base58
import json
from werkzeug.http import parse_cookie, dump_cookie
from werkzeug.wsgi import ClosingIterator

REDIRECT_HTML = """<!DOCTYPE HTML>
<html lang="en-US">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="1;url=REDIRECT_ME">
        <script type="text/javascript">
            window.location.href = "REDIRECT_ME"
        </script>
        <title>Page Redirection</title>
    </head>
    <body>
        <!-- Note: don't tell people to `click` the link, just tell them that it is a link. -->
        If you are not redirected automatically, follow the <a href='REDIRECT_ME'>link to example</a>
    </body>
</html>"""

class ZappaWSGIMiddleware(object):

    # Unpacked / Before Packed Cookies 
    decoded_zappa = None
    request_cookies = {}

    start_response = None
    redirect_content = None

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        """
        A note about the zappa cookie: Only 1 cookie can be passed through API
        Gateway. Hence all cookies are packed into a special cookie, the
        zappa cookie. There are a number of problems with this:

            * updates of single cookies, when there are multiple present results
              in deletion of the ones that are not being updated.
            * expiration of cookies. The client no longer knows when cookies
              expires.

        The first is solved by unpacking the zappa cookie on each request and
        saving all incoming cookies. The response Set-Cookies are then used
        to update the saved cookies, which are packed and set as the zappa
        cookie.

        The second is solved by filtering cookies on their expiration time,
        only passing cookies that are still valid to the WSGI app.
        """
        self.start_response = start_response

        # Parse cookies from the WSGI environment
        parsed = parse_cookie(environ)

        # Decode the special zappa cookie if present in the request
        if 'zappa' in parsed:
            # Save the parsed cookies. We need to send them back on every update.
            self.decode_zappa_cookie(parsed['zappa'])
            # Set the WSGI environment cookie to be the decoded value.
            environ[u'HTTP_COOKIE'] = self.decoded_zappa
        else:
            # No cookies were previously set
            self.request_cookies = dict()

        return ClosingIterator(
            self.application(environ, self.encode_response)
        )

    def encode_response(self, status, headers, exc_info=None):
        """
        Zappa-ify our application response!

        This means:
            - Updating any existing cookies.
            - Packing all our cookies into a single ZappaCookie.
            - Injecting redirect HTML if setting a Cookie on a redirect.

        """

        # All the non-cookie headers should be sent unharmed.
        new_headers = [(header[0], header[1]) for header in headers if header[0] != 'Set-Cookie']

        # Filter the headers for Set-Cookie header
        cookie_dicts = [parse_cookie(x[1]) for x in headers if x[0] == 'Set-Cookie']
        
        # Flatten cookies_dicts to one dict. If there are multiple occuring
        # cookies, the last one present in the headers wins.
        new_cookies = dict()
        map(new_cookies.update, cookie_dicts)

        # Update request_cookies with cookies from the response.
        for name, value in new_cookies.items():
            self.request_cookies[name] = value

        # JSON-ify the cookie and encode it.
        pack_s = json.dumps(self.request_cookies)
        encoded = base58.b58encode(pack_s)
        
        # Set the result as the zappa cookie
        new_headers.append(
            ('Set-Cookie', dump_cookie('zappa', value=encoded))
        )

        # If setting cookie on a 301/2,
        # return 200 and replace the content with a javascript redirector
        if status != '200 OK':
            for key, value in new_headers:
                if key != 'Location':
                    continue
                redirect_content = REDIRECT_HTML.replace('REDIRECT_ME', value)
                status = '200 OK'
                break

        self.write = self.start_response(status, new_headers, exc_info)
        return self.zappa_write

    def zappa_write(self, body_data):
        """
        Modify the response body with our redirect injection.
        """
        if redirect_content:
            self.write(redirect_content)
        else:
            self.write(body_data)        

    def decode_zappa_cookie(self, encoded_zappa):
        """
        Eat our Zappa cookie.
        Save the parsed cookies, as we need to send them back on every update.

        """

        self.decoded_zappa = base58.b58decode(encoded_zappa)
        self.request_cookies = json.loads(self.decoded_zappa)
        return
