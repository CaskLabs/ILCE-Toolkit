"""A wrapper to use libusb. Default on linux, on Windows you have to install a generic driver for your camera"""

import usb.core
import usb.util
import sys
import os
from functools import wraps

from . import *

class UsbCaptureRequired(usb.core.USBError):
 """A real macOS mass-storage kernel driver requires authorized capture."""
 requires_administrator = True

class UsbCaptureBlocked(usb.core.USBError):
 """Capture was authorized but macOS still rejects the storage interface."""
 requires_full_disk_access = True

def _usb_access(method):
 """Use the authorized helper's real uid only while accessing IOKit/USB."""
 @wraps(method)
 def wrapped(self, *args, **kwargs):
  effective_uid = None
  if sys.platform == 'darwin' and os.getuid() == 0:
   effective_uid = os.geteuid()
   if effective_uid != 0:
    os.seteuid(0)
  try:
   return method(self, *args, **kwargs)
  finally:
   if effective_uid is not None and os.geteuid() != effective_uid:
    os.seteuid(effective_uid)
 return wrapped

class _UsbContext(BaseUsbContext):
 def __init__(self, name, classType, driverClass):
  super(_UsbContext, self).__init__('libusb-%s' % name, classType)
  self._driverClass = driverClass
  self._backends = []

 def __exit__(self, *ex):
  try:
   for backend in self._backends:
    backend.close()
  finally:
   self._backends = []

 def _openBackend(self, device):
  backend = UsbBackend(device.handle)
  self._backends.append(backend)
  return backend

 def listDevices(self, vendor):
  return _listDevices(vendor, self.classType)

 def openDevice(self, device):
  return self._driverClass(self._openBackend(device))


class MscContext(_UsbContext):
 def __init__(self):
  super(MscContext, self).__init__('MSC', USB_CLASS_MSC, None)

 def openDevice(self, device):
  backend = self._openBackend(device)
  interface = next((interface for config in device.handle for interface in config), None)
  if interface.bInterfaceProtocol in (0, 1):
   return MscCbiDriver(backend)
  elif interface.bInterfaceProtocol == 0x50:
   return MscBbbDriver(backend)
  else:
   raise Exception('Invalid protocol')

class MtpContext(_UsbContext):
 def __init__(self):
  super(MtpContext, self).__init__('MTP', USB_CLASS_PTP, MtpDriver)

class VendorSpecificContext(_UsbContext):
 def __init__(self):
  super(VendorSpecificContext, self).__init__('vendor-specific', USB_CLASS_VENDOR_SPECIFIC, GenericUsbDriver)


def _listDevices(vendor, classType):
 """Lists all detected USB devices"""
 for dev in usb.core.find(find_all=True, idVendor=vendor):
  interface = next((interface for config in dev for interface in config), None)
  if interface and interface.bInterfaceClass == classType:
   yield UsbDeviceHandle(dev, dev.idVendor, dev.idProduct)


class UsbBackend(BaseUsbBackend):
 """Bulk reading and writing to USB devices"""

 def __init__(self, device):
  self.dev = device
  self.dev.default_timeout = 5000
  self._closed = False
  self._detached = False

 def __del__(self):
  try:
   self.close()
  except Exception:
   pass

 @_usb_access
 def close(self):
  if not self._closed:
   try:
    if self._detached:
     try:
      usb.util.release_interface(self.dev, 0)
     except usb.core.USBError as error:
      # Entering/leaving service mode removes the old USB identity.
      if error.errno != 19 and error.backend_error_code != -4:
       raise
     try:
      self._capture(self.dev.attach_kernel_driver)
     except usb.core.USBError:
      # Mode switches can disconnect the old mass-storage USB device.
      pass
   finally:
    try:
     usb.util.dispose_resources(self.dev)
    finally:
     self._closed = True

 def _capture(self, operation):
  effective_uid = os.geteuid()
  try:
   if effective_uid != 0:
    os.seteuid(0)
   return operation(0)
  finally:
   if os.geteuid() != effective_uid:
    os.seteuid(effective_uid)

 def getId(self):
  return self.dev.idVendor, self.dev.idProduct

 @_usb_access
 def getEndpoints(self):
  return self.dev.get_active_configuration()[(0, 0)]

 @_usb_access
 def reset(self):
  if sys.platform == 'darwin':
   # Darwin's driver check treats any IORegistry child as a kernel driver,
   # including our own USB user client. Claiming is idempotent in PyUSB and
   # avoids both a privileged device capture and a release/reclaim race.
   try:
    usb.util.claim_interface(self.dev, 0)
   except usb.core.USBError as error:
    interface = self.dev.get_active_configuration()[(0, 0)]
    if (error.errno not in (13, 16) and error.backend_error_code not in (-3, -6, -99)) or interface.bInterfaceClass != USB_CLASS_MSC or not self.dev.is_kernel_driver_active(0):
     raise
    if os.getuid() != 0:
     raise UsbCaptureRequired('macOS-Massenspeichertreiber belegt das USB-Interface.', errno=13) from error
    def capture_and_claim(interface):
     self.dev.detach_kernel_driver(interface)
     self._detached = True
     usb.util.claim_interface(self.dev, interface)
    try:
     self._capture(capture_and_claim)
    except usb.core.USBError as capture_error:
     if self._detached and capture_error.backend_error_code in (-3, -99):
      raise UsbCaptureBlocked('macOS verweigert das Massenspeicher-Interface trotz Administratorfreigabe.') from capture_error
     raise
   return
  try:
   if self.dev.is_kernel_driver_active(0):
    self.dev.detach_kernel_driver(0)
  except NotImplementedError:
   pass

 @_usb_access
 def clearHalt(self, ep):
  self.dev.clear_halt(ep)

 @_usb_access
 def read(self, ep, length, timeout=None):
  try:
   return self.dev.read(ep, length, timeout).tobytes()
  except usb.core.USBError:
   raise GenericUsbException()

 @_usb_access
 def write(self, ep, data):
  try:
   self.dev.write(ep, data)
  except usb.core.USBError:
   raise GenericUsbException()

 @_usb_access
 def classInterfaceRequestOut(self, request, value, index, data=b''):
  try:
   self.dev.ctrl_transfer(usb.util.CTRL_OUT | usb.util.CTRL_TYPE_CLASS | usb.util.CTRL_RECIPIENT_INTERFACE, request, value, index, data)
  except usb.core.USBError as e:
   raise GenericUsbException()

 @_usb_access
 def vendorRequestOut(self, request, value, index, data=b''):
  try:
   self.dev.ctrl_transfer(usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_OTHER, request, value, index, data)
  except usb.core.USBError as e:
   raise GenericUsbException()
