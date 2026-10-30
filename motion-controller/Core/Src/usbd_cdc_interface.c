#include "usbd_cdc_interface.h"

#include <string.h>

#include "usb_device.h"

#define APP_RX_DATA_SIZE  64U
#define APP_TX_DATA_SIZE  64U

static uint8_t UserRxBufferFS[APP_RX_DATA_SIZE];
static uint8_t UserTxBufferFS[APP_TX_DATA_SIZE];

static uint8_t LineCoding[7] = {
  0x00U, 0xC2U, 0x01U, 0x00U, /* 115200 bit/s */
  0x00U,                       /* 1 stop bit */
  0x00U,                       /* no parity */
  0x08U                        /* 8 data bits */
};

static int8_t CDC_Init_FS(void);
static int8_t CDC_DeInit_FS(void);
static int8_t CDC_Control_FS(uint8_t command, uint8_t *buffer, uint16_t length);
static int8_t CDC_Receive_FS(uint8_t *buffer, uint32_t *length);

USBD_CDC_ItfTypeDef USBD_CDC_fops = {
  CDC_Init_FS,
  CDC_DeInit_FS,
  CDC_Control_FS,
  CDC_Receive_FS
};

static int8_t CDC_Init_FS(void)
{
  USBD_CDC_SetTxBuffer(&USBD_Device, UserTxBufferFS, 0U);
  USBD_CDC_SetRxBuffer(&USBD_Device, UserRxBufferFS);
  return (int8_t)USBD_OK;
}

static int8_t CDC_DeInit_FS(void)
{
  return (int8_t)USBD_OK;
}

static int8_t CDC_Control_FS(uint8_t command, uint8_t *buffer, uint16_t length)
{
  (void)length;

  if (command == CDC_SET_LINE_CODING)
  {
    memcpy(LineCoding, buffer, sizeof(LineCoding));
  }
  else if (command == CDC_GET_LINE_CODING)
  {
    memcpy(buffer, LineCoding, sizeof(LineCoding));
  }

  return (int8_t)USBD_OK;
}

static int8_t CDC_Receive_FS(uint8_t *buffer, uint32_t *length)
{
  (void)length;
  USBD_CDC_SetRxBuffer(&USBD_Device, buffer);
  USBD_CDC_ReceivePacket(&USBD_Device);
  return (int8_t)USBD_OK;
}

uint8_t CDC_Transmit_FS(uint8_t *buffer, uint16_t length)
{
  USBD_CDC_HandleTypeDef *cdc_handle;

  if ((USBD_Device.dev_state != USBD_STATE_CONFIGURED) ||
      (USBD_Device.pClassData == NULL))
  {
    return USBD_BUSY;
  }

  cdc_handle = (USBD_CDC_HandleTypeDef *)USBD_Device.pClassData;
  if (cdc_handle->TxState != 0U)
  {
    return USBD_BUSY;
  }

  USBD_CDC_SetTxBuffer(&USBD_Device, buffer, length);
  return USBD_CDC_TransmitPacket(&USBD_Device);
}
