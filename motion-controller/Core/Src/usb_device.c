#include "usb_device.h"

#include "main.h"
#include "usbd_cdc.h"
#include "usbd_cdc_interface.h"
#include "usbd_core.h"
#include "usbd_desc.h"

USBD_HandleTypeDef USBD_Device;

void MX_USB_DEVICE_Init(void)
{
  if (USBD_Init(&USBD_Device, &VCP_Desc, 0U) != USBD_OK)
  {
    Error_Handler();
  }

  if (USBD_RegisterClass(&USBD_Device, USBD_CDC_CLASS) != USBD_OK)
  {
    Error_Handler();
  }

  if (USBD_CDC_RegisterInterface(&USBD_Device, &USBD_CDC_fops) != USBD_OK)
  {
    Error_Handler();
  }

  if (USBD_Start(&USBD_Device) != USBD_OK)
  {
    Error_Handler();
  }
}
