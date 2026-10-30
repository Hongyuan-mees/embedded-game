#ifndef __USB_DEVICE_H__
#define __USB_DEVICE_H__

#ifdef __cplusplus
extern "C" {
#endif

#include "usbd_def.h"

extern USBD_HandleTypeDef USBD_Device;

void MX_USB_DEVICE_Init(void);

#ifdef __cplusplus
}
#endif

#endif /* __USB_DEVICE_H__ */
