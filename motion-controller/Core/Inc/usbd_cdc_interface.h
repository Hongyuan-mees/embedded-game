#ifndef __USBD_CDC_INTERFACE_H__
#define __USBD_CDC_INTERFACE_H__

#ifdef __cplusplus
extern "C" {
#endif

#include "usbd_cdc.h"

extern USBD_CDC_ItfTypeDef USBD_CDC_fops;

uint8_t CDC_Transmit_FS(uint8_t *buffer, uint16_t length);

#ifdef __cplusplus
}
#endif

#endif /* __USBD_CDC_INTERFACE_H__ */
