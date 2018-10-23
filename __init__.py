import re
import time
import paramiko

class Expect(object):
	def __init__(self, host, username, password, port=22, terminator="#"):
		self._host 		= host
		self._username 	= username
		self._password 	= password
		self._port		= port
		self._prompt	= None
		self._ssh		= None
		self._chan		= None
		self._connected = False
		self._terminator = terminator

	def connect(self, wait_timeout=10, connect_timeout=180):
		"""
		Connect to the management module, with the host, username, and password settings

		:param int connect_timeout: How long to try to connect for before stopping
		:param int wait_timeout: How long to wait before trying to connect to the host
		:return: Whether or not the connection was successful
		:rtype: bool
		"""
		start_time = time.time()
		try:
			self._ssh = paramiko.SSHClient()
			self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
			self._ssh.connect(self._host, self._port, self._username, self._password)
			self._chan = self._ssh.invoke_shell()
		except Exception as e:
			print("Unable to connect to {host}@{port} with user {username}: {error}".format(
				host=self._host,
				port=self._port,
				username=self._username,
				error=e))
			return False

		while True:
			response = None
			try:
				response = self.send(wait_for_prompt=False)

				self._chan.resize_pty(height=500)
				# self._prompt = "".join(out).replace(self._terminator, "").strip()
				tmp = response[-1].strip()
				self._prompt = response[-1].rstrip(self._terminator).strip()
				if tmp == self._prompt:
					self._terminator = self._prompt[-1]
					self._prompt = self._prompt.rstrip(self._terminator)
				self._connected = True
				return True
			except Exception as e:
				print("Error while connecting {response}: {error}".format(response=response, error=e))
				if time.time() - start_time > connect_timeout:
					return False
				time.sleep(wait_timeout)

	def disconnect(self):
		"""Disconnect the session to the management module"""
		if self._ssh:
			self._ssh.close()
			self._chan = None
			self._connected = False

	def is_connected(self, reconnect=True):
		"""
		Whether or not the connection to the IMS is active.

		:param bool reconnect: Whether or not it should try to reconnect if not active
		:return: Whether or not the connection is active
		:rtype: bool
		"""
		transport 		= self._ssh.get_transport() if self._ssh else None
		self._connected = transport and transport.is_active()
		if not self._connected and reconnect:
			self.connect()
		return self._connected

	def send(self, cmd="", wait=2, wait_for_prompt=True, prompt=None):
		"""
		Sends a command to the connected server

		:param string cmd: Command to send
		:param int wait: Amount of time (in seconds) to wait after sending first command
		:param bool wait_for_prompt: Whether or not to wait for a prompt to be returned
		:param string prompt: Override search prompt
		:return: Response from the server after the command is sent
		:rtype: string
		"""
		if prompt is None:
			prompt = self._prompt

		if wait_for_prompt:
			out, status = self.execute_command(
				cmd.strip(),
				search="{prompt}.*?{terminator}".format(prompt=prompt, terminator=self._terminator),
				chan=self._chan)
		else:
			out, status = self.execute_command(cmd.strip(), wait=wait, chan=self._chan)

		lines = out.strip().split("\r\n")
		if len(lines) <= 2:
			return lines

		lines = lines[1:-1]
		if lines and not lines[-1].strip():
			return lines[:-1]
		return lines

	def execute_command(self, cmd, search=None, wait=0, timeout=60, return_status=False, chan=None):
		"""
		IMPROVED!!! Executes a ssh command and waits for a response based on certain critera

		:param paramiko.chan chan: SSH channel object to use
		:param string cmd: Command to execute
		:param string search: String to search for in the response
		:param int wait: Amount of time to wait before checking for a response
		:param int timeout: Amount of time to wait (in seconds) before timing out
		:param bool return_status: Whether or not to return the status of the command as well
		:return: The result from running the command
		:rtype: string
		"""
		result = ""
		status = 0

		if chan is None:
			chan = self._chan

		if not chan.transport.is_active():
			if chan == self._chan:
				if not self.connect():
					raise Exception("Connection has been lost")
			else:
				raise Exception("Connection has been lost")

		chan.send("{cmd}\r".format(cmd=cmd))
		if wait > 0:
			time.sleep(wait)

		start_time = time.time()
		while not chan.recv_ready():
			time.sleep(.1)
			wait_time = time.time() - start_time
			if wait_time > timeout:
				return result, status

		search_time = 0
		if search is not None:
			start_time = time.time()
			matches = re.findall(search, result)
			while len(matches) < 1 and search_time < timeout:
				time.sleep(.1)
				search_time = time.time() - start_time
				if chan.recv_ready():
					result += chan.recv(1024)
				matches = re.findall(search, result)
		else:
			while chan.recv_ready():
				time.sleep(.1)
				result += chan.recv(1024)

		if return_status:
			chan.send("echo $?\r")
			while not chan.recv_ready():
				time.sleep(.1)
			while chan.recv_ready():
				time.sleep(.1)
				status += chan.recv(1024)
			try:
				status = int(status.split("\n")[1])
			except Exception:
				status = -1
		return result, status
